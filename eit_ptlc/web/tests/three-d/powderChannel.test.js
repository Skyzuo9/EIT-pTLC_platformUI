/**
 * 功能: 粉桶内容物 `powder` 连续通道 —— 编译、插值、驱动层写入与清场.
 *
 * 与 pump/liquid 两条同类通道的**三处不同**, 每一处都有对应的用例钉住:
 *   1. 单位是 **mm³** 不是 mL —— 量的来源是"轮廓面积 × 切深 × 松散系数", 天生立方毫米。
 *      高度换算留在写入层(按腔体自由截面积与观感放大系数), 片段里只有体积。
 *   2. 两条相位共享 id: `fill`(粉量)与 `tint`(洗脱色 0..1)。它们是**同一件物的两个
 *      自由度**, 必须成对交付 —— evaluateChannels 因此按 id 汇成 {fill, tint}。
 *   3. 落点**恒锚在腔的 c1 端**(吹气头那一头): 粉被滤纸内衬拦着, 桶翻 180° 倒粉时粉
 *      跟着桶转、相对桶纹丝不动。于是 updatePowders 的位姿趟不吃任何姿态输入。
 *
 * 防漂主测: 驱动层写出的粉柱几何必须与实时链(TwinBindings._updateConsumablePowders)
 * 逐位一致 —— 共享数学全在 powderPivot.js 的模块级纯函数里, 两边都只准调它。
 */
import assert from 'node:assert/strict'
import test from 'node:test'
import * as THREE from 'three'

import { compileClip, evaluateChannels } from '../../src/three-d/anim/clipSchema.js'
import { MachineStateDriver } from '../../src/three-d/anim/MachineStateDriver.js'
import { applyPowderColumn, levelFromMm3 } from '../../src/three-d/twin/bindings/powderPivot.js'
import { captureLiquidBase } from '../../src/three-d/twin/bindings/liquidPivot.js'

/** 腔段: 与 rig_map 实测同形(滤纸内衬孔的等径段, item 局部 [+5.0, +78.0]mm ⇒ 自由腔 73mm) */
const CHAMBER = { c0: 0.005, c1: 0.078 }
/** 内衬孔 Ø18.4 ⇒ 自由截面 265.9mm²; 腔深 73mm ⇒ 容量 19410.7mm³ */
const CAVITY = { usableDepthMm: 73, freeAreaMm2: 265.9, capacityMm3: 19410.7, mm3PerMm: 265.9 }
const POWDER_NODE = 'ST_PHOTOSCRAPE/ACTUATOR_PS_ROTATE/硅胶收集-1.008/POWDER_SCRAPE_HOLDER'

/** 一段"逐刀吸粉 → 洗脱换色"的最小片段(形状照 clip_compiler 真实产出) */
function scrapeClip() {
  return {
    schema: 'ptlc.clip/v1',
    name: 'powder_fill',
    home: { powder_mm3: { pw: 0 } },
    steps: [
      { label: '收集·粉进桶(累计 1/2)', dur: 6, ease: 'linear', do: { powder: { id: 'pw', phase: 'fill', to: 384 } } },
      { label: '收集·粉进桶(累计 2/2)', dur: 6, ease: 'linear', do: { powder: { id: 'pw', phase: 'fill', to: 768 } } },
      { label: '收集·洗脱液浸透硅胶粉', dur: 6, ease: 'out', do: { powder: { id: 'pw', phase: 'tint', to: 1 } } },
    ],
  }
}

/**
 * 造一根粉柱 + 最小 manifest.
 *
 * 粉柱建模位 scale.z=1(满腔), 材质独占一份的义务由驱动层承担 —— 这里给一份**共用**
 * 材质, 用例据此验出"驱动层真的克隆了", 而不是就地改共用材质把别的桶一起染色。
 */
function makePowderRig({ withNode = true, elutedColor = '#8a7d6b' } = {}) {
  const root = new THREE.Group()
  const nodes = new Map()
  const shared = new THREE.MeshStandardMaterial({ color: '#e8e4dc' })

  // 桶本体: 粉柱挂在它下面, 翻料时随它转 —— "翻转后落点不动"那条用例靠的就是这一层
  const holder = new THREE.Group()
  holder.name = '硅胶收集-1.008'
  root.add(holder)

  const column = new THREE.Mesh(new THREE.CylinderGeometry(0.0092, 0.0092, 0.073, 8), shared)
  column.name = 'POWDER_SCRAPE_HOLDER'
  holder.add(column)
  root.updateMatrixWorld(true)
  if (withNode) nodes.set(POWDER_NODE, column)

  const manifest = {
    consumableContents: {
      kinds: [
        {
          id: 'pw',
          kind: 'powder',
          node: POWDER_NODE,
          seat: 'scrape-holder',
          cavity: CAVITY,
          chamber: CHAMBER,
          exaggeration: 6,
          bulkFactor: 1.6,
          elutedColor,
        },
        // 液体类内容物不该被粉的绑定收走(kind 过滤的看门)
        { id: 'liq_x', kind: 'liquid', node: POWDER_NODE, seat: 'x' },
      ],
    },
  }
  const rig = new MachineStateDriver({ manifest, resolve: (p) => nodes.get(p) })
  return { rig, column, holder, shared, manifest }
}

test('powder 是连续通道: 两条相位各自成通道, 编译进 channels 而不是 events', () => {
  const clip = compileClip(scrapeClip())
  assert.equal(clip.events.length, 0, '粉不该产生离散事件')
  assert.ok(clip.channels.has('powder:pw:fill'))
  assert.ok(clip.channels.has('powder:pw:tint'))
})

test('粉量/洗脱色按关键帧插值, 任意 t 都是纯函数(seek 安全)', () => {
  const clip = compileClip(scrapeClip())
  const at = (t) => evaluateChannels(clip, t)

  assert.equal(at(0).powders.pw.fill, 0, 't=0 是 home 声明的起始粉量')
  assert.equal(at(0).powders.pw.tint, 0, '未洗是粉的中性态')
  const mid = at(3).powders.pw.fill
  assert.ok(mid > 0 && mid < 384, '第一刀中途在两端之间')
  assert.equal(at(6).powders.pw.fill, 384, '第一刀收尽')
  assert.equal(at(12).powders.pw.fill, 768, '第二刀收尽(逐刀累加)')
  assert.equal(at(18).powders.pw.tint, 1, '洗脱后换色到位')
  assert.equal(at(99).powders.pw.fill, 768, '播完保持终值')
  for (const t of [0.2, 5, 10.3, 13.5, 30]) {
    assert.equal(at(t).powders.pw.fill, at(t).powders.pw.fill, `t=${t} 求值不稳定`)
  }
})

test('只在 home.powder_mm3 里声明、没有任何步骤的桶也要建通道(收集段起手不许演空桶)', () => {
  // 与泵的"起手气隙"、液面的"起手满缸"同一形状: rig.home() 把粉一律清零, 只声明不驱动
  // 的桶不建通道就会开局回 0 —— 而 collect_unload 里那只桶正是上一段留下的。
  const clip = compileClip({
    schema: 'ptlc.clip/v1',
    name: 'hold_powder',
    home: { powder_mm3: { pw: 768 }, powder_tint: { pw: 1 } },
    steps: [{ label: '等待', dur: 2, do: { wait: {} } }],
  })
  assert.ok(clip.channels.has('powder:pw:fill'), 'home 里声明的粉必须各自成一条通道')
  assert.ok(clip.channels.has('powder:pw:tint'))
  assert.equal(evaluateChannels(clip, 0).powders.pw.fill, 768)
  assert.equal(evaluateChannels(clip, 2).powders.pw.fill, 768, '没人驱动就一直保持声明值')
  assert.equal(evaluateChannels(clip, 2).powders.pw.tint, 1, '起手就是洗过的粉')
})

test('老片段(没有 tint 通道)读成"未洗"而不是被当成缺省错值', () => {
  // 与 scrape 的 pass 相位**刻意相反**: 那里 0 是老片段的错读(会永远刮不透), 而粉的
  // 0 就是物理上正确的中性态 —— 老片段照播, 不需要任何兼容分支。
  const clip = compileClip({
    schema: 'ptlc.clip/v1',
    name: 'old',
    steps: [{ label: '吸粉', dur: 4, do: { powder: { id: 'pw', phase: 'fill', to: 500 } } }],
  })
  assert.equal(clip.channels.has('powder:pw:tint'), false, '没人写 tint 就不该凭空建通道')
  assert.equal(evaluateChannels(clip, 4).powders.pw.tint, 0, '缺 tint 通道读成未洗')
  assert.equal(evaluateChannels(clip, 4).powders.pw.fill, 500)
})

test('powder 参数非法在编译期就报错', () => {
  const build = (body) => () => compileClip({
    schema: 'ptlc.clip/v1',
    name: 'bad',
    steps: [{ label: 'x', dur: 1, do: { powder: body } }],
  })
  assert.throws(build({ phase: 'fill', to: 1 }), /缺 id\/phase\/to/)
  assert.throws(build({ id: 'pw', to: 1 }), /缺 id\/phase\/to/)
  assert.throws(build({ id: 'pw', phase: 'fill' }), /缺 id\/phase\/to/)
  assert.throws(build({ id: 'pw', phase: 'colour', to: 1 }), /必须是 fill \/ tint/)
  assert.throws(build({ id: 'pw', phase: 'fill', to: -1 }), /非负 mm³/)
  assert.throws(build({ id: 'pw', phase: 'tint', to: 1.5 }), /0\.\.1 的洗脱色相位/)
  assert.throws(build({ id: 'pw', phase: 'tint', to: -0.1 }), /0\.\.1 的洗脱色相位/)
})

test('id 里带冒号也能拆对相位(从右侧拆, 不对 id 字符集做假设)', () => {
  const clip = compileClip({
    schema: 'ptlc.clip/v1',
    name: 'weird',
    steps: [{ label: 'x', dur: 1, do: { powder: { id: 'a:b:c', phase: 'fill', to: 12 } } }],
  })
  assert.equal(evaluateChannels(clip, 1).powders['a:b:c'].fill, 12)
})

test('驱动层: 粉量按 mm³ 写入, 高度换算与实时链逐位相同(防漂主测)', () => {
  const { rig, column } = makePowderRig()
  const base = captureLiquidBase(column)

  for (const mm3 of [0, 384, 768, 5000]) {
    rig.updatePowders({ pw: { fill: mm3, tint: 0 } })
    assert.equal(rig.powderMm3('pw'), mm3, '面板值是真实 mm³, 不含观感放大')

    // 期望值走的是**同一份纯函数**, 与 TwinBindings._updateConsumablePowders 同源
    const probe = new THREE.Mesh(column.geometry.clone(), column.material.clone())
    probe.position.copy(base.basePosition)
    probe.scale.copy(base.baseScale)
    const level = levelFromMm3(CAVITY, mm3, 6)
    applyPowderColumn(base, probe, CHAMBER, level)
    assert.ok(column.position.distanceTo(probe.position) < 1e-12, `${mm3}mm³: 粉柱位置漂了`)
    // 缩放轴是节点**局部 Y**(applyLiquidLevel 只动 scale.y) —— 与液柱同一条约定:
    // 管线建的是 Blender 局部 Z 向圆柱, 导出 glTF 后 Z-up→Y-up, 筒轴落在局部 Y 上。
    assert.ok(Math.abs(column.scale.y - probe.scale.y) < 1e-12, `${mm3}mm³: 粉柱高度漂了`)
  }
})

test('粉量不夹容量: 超腔容自然饱和到满腔而不是被截成别的数', () => {
  // 与 setLiquidMl 的**唯一分歧**: 腔容是目标自己的几何事实, 夹在写入层会让"桶满了"
  // 与"账本记了多少"两件事纠缠, 而面板要显示的是后者。
  const { rig, column } = makePowderRig()
  const base = captureLiquidBase(column)
  rig.updatePowders({ pw: { fill: 999999, tint: 0 } })
  assert.equal(rig.powderMm3('pw'), 999999, '账本值原样保留')
  assert.ok(Math.abs(column.scale.y - base.baseScale.y) < 1e-9, '几何饱和在满腔(level=1)')
})

test('翻转 180°: 粉恒定贴 c1 端(吹气头那一头), 相对桶纹丝不动', () => {
  const { rig, column, holder } = makePowderRig()
  const level = levelFromMm3(CAVITY, 768, 6)
  const height = (CHAMBER.c1 - CHAMBER.c0) * level
  const base = captureLiquidBase(column)
  // 粉柱底面的期望局部坐标: applyPowderColumn 把 basePosition.y 定成 y0 − baseMinY,
  // 而 applyLiquidLevel 又沿 +Y 补 baseMinY×(1−factor) —— 合成后底面恰在 y0。
  const bottomOf = () => column.position.y + base.baseMinY * level

  assert.ok(level > 0.05 && level < 0.95, '用例前提: 半满而不是空/满(空/满看不出落点)')

  rig.updatePowders({ pw: { fill: 768, tint: 0 } })
  const uprightBottom = bottomOf()
  // 占位区间恒为 [c1−h, c1] ⇒ 底面在 c1−h
  assert.ok(Math.abs(uprightBottom - (CHAMBER.c1 - height)) < 1e-6,
    `粉应贴 c1 端(底面 ${CHAMBER.c1 - height}), 实得 ${uprightBottom}`)

  // 翻过来: 桶转 180°(与 ps_rotate 倒粉同一个姿态)。粉被滤纸内衬拦着, 跟着桶一起转,
  // 局部落点**必须一位不差** —— 这条正是用户"始终靠近尾部, 无论是否反转"的看门狗。
  holder.rotation.set(Math.PI, 0, 0)
  holder.updateMatrixWorld(true)
  rig.updatePowders({ pw: { fill: 768, tint: 0 } })
  assert.ok(Math.abs(bottomOf() - uprightBottom) < 1e-12,
    `翻转后落点漂了: ${uprightBottom} -> ${bottomOf()}`)
})

test('tint 写色必须克隆材质: 不许把共用材质连坐染色', () => {
  // 离线链 _bindLiquids/_bindPumps 有意不克隆(它们一个颜色都不写), 而粉要写色 ——
  // 触发的正是 _bindLiquids 头注释留的那句"真要写颜色时照 _bindLight 克隆并配对释放"。
  // 不克隆的后果: 货架上另外 5 只桶跟着变色, 且没有任何指标会报警。
  const { rig, column, shared } = makePowderRig()
  assert.notEqual(column.material, shared, '绑定时就该换成克隆件')

  const before = column.material.color.clone()
  rig.updatePowders({ pw: { fill: 768, tint: 1 } })
  assert.ok(column.material.color.getHex() !== before.getHex(), '洗脱后必须换色')
  assert.equal(shared.color.getHex(), 0xe8e4dc, '共用材质一个通道都不许被改')
})

test('契约没给洗脱色时静默不写色(缺声明的降级是"粉还在, 只是不换色")', () => {
  const { rig, column } = makePowderRig({ elutedColor: '' })
  const before = column.material.color.getHex()
  rig.updatePowders({ pw: { fill: 768, tint: 1 } })
  assert.equal(column.material.color.getHex(), before, '没有洗脱色就不该乱写')
})

test('缺节点的粉桶走降级路径: 通道照样求值, 三维不动也不报错', () => {
  // 与泵 rigged:false 同一条路径 —— 数据仍在, 只是没有几何可写。
  // 这正是"粉柱几何还没进管线时片段照编、前端空跑"的依据。
  const { rig } = makePowderRig({ withNode: false })
  assert.equal(rig.powders.size, 0, '解析不到节点就不建条目')
  assert.doesNotThrow(() => rig.updatePowders({ pw: { fill: 768, tint: 1 } }))
  assert.equal(rig.powderMm3('pw'), 0)
})

test('home() 把粉清零并复位未洗色 —— 向后 seek 的清场不许只清一半', () => {
  const { rig, column } = makePowderRig()
  rig.updatePowders({ pw: { fill: 768, tint: 1 } })
  const dirty = column.material.color.getHex()

  rig.home()
  assert.equal(rig.powderMm3('pw'), 0, '空桶才是这台机器的静止态')
  assert.equal(column.visible, false, '空桶不该留一张压扁的顶面')
  assert.notEqual(column.material.color.getHex(), dirty, 'tint 也要回未洗, 否则空桶却是洗过色')
})

test('dispose(): 粉柱几何成对还原, 且克隆的材质被释放', () => {
  const { rig, column } = makePowderRig()
  const scale0 = column.scale.clone()
  const pos0 = column.position.clone()
  rig.updatePowders({ pw: { fill: 768, tint: 1 } })

  let disposed = false
  column.material.dispose = () => { disposed = true }
  rig.dispose()

  assert.ok(disposed, '克隆一次就有一份配对的释放义务')
  assert.ok(column.scale.distanceTo(scale0) < 1e-12, 'scale 要还原到加载态')
  assert.ok(column.position.distanceTo(pos0) < 1e-12, 'position 必须与 scale 一起还原(否则越用越歪)')
  assert.equal(rig.powders.size, 0)
})

test('刚体门禁刻意不含粉柱 —— 它天生就是靠非单位缩放表达粉量的', () => {
  const { rig, column } = makePowderRig()
  rig.updatePowders({ pw: { fill: 384, tint: 0 } })
  assert.ok(Math.abs(column.scale.y - 1) > 1e-6, '用例前提: 此刻确实是非单位缩放')
  assert.equal(rig.rigidScaleViolations().includes('POWDER_SCRAPE_HOLDER'), false,
    '顺手"补全"这个门禁会让它在粉上线当天变红, 而红的不是缺陷')
})
