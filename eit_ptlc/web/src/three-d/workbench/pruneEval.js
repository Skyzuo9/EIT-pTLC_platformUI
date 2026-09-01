/**
 * 功能: 求"会被管线删掉"的零件集合 —— 白模标红与「减配后」隐藏共用.
 *
 * 裁决由管线出, 这里只做两件事: 把基线(work/prune_preview.json)里的节点名展开成
 * 索引键, 再叠加用户**尚未保存**的显式标记.
 *
 * 为什么不再自己算规则: 这里原本是 blender_clean.prune 的浏览器再实现, 与管线漂移出
 * 四类错判(2026-08-05 定位) ——
 *   1. 拼音别名表覆盖不同: 管线用 pypinyin 对模型里每个中文名现算, 浏览器只能查
 *      names.csv(309 行 STEP 时代产品名表), `zhi_shi_deng` 这类 keep 规则永远命不中;
 *   2. 尺寸口径不同: 管线取零件自身局部包围盒(obj.dimensions), 这里取子树世界 AABB,
 *      旋转件世界盒恒偏大, 会漏红一批管线真会按尺寸删掉的零件;
 *   3. 管线在 prune **之后**才造的合成零件(注射泵指示灯等)根本没经过删减, 却被这里
 *      当普通小零件套上尺寸阈值, 于是三颗指示灯常年顶着红色;
 *   4. region_delete 是**面级**删除, 节点粒度表达不了"只删线不删电机" —— 电机上那截
 *      注定被删的模制线缆一直是白的.
 * 前三条由基线一次性解决; 第 4 条靠管线在 raw 阶段把面岛分离成独立节点(见
 * blender_clean.region_split), 到了这里它就是个普通节点, 不需要任何特例.
 *
 * 基线缺失或与当前 prune_list.yaml 对不上时**退化**为下面的近似算法, 由 previewStatus()
 * 判出状态让页面挂告警 —— 与片段陈旧检测(clipSchema.railCalibStatus)同一约定:
 * 缺戳一律不许判绿.
 *
 * 优先级(高到低): 显式保留 > 显式删除 > 正则保留(keep_patterns) >
 * 正则删除(delete_patterns) > 尺寸阈值(min_dimension_mm); 基线判定占"正则删除"那一档.
 * 用分数编码而不是"keep 一律豁免"的布尔式: 布尔式会让正则保留挡住显式删除, 违反次序.
 * keep/delete 两个分数各自沿子树取 max 下传(删一个装配连带整棵子树, 保留同理),
 * 尺寸分只对叶子生效且不下传. 节点判删 = deleteScore > keepScore.
 *
 * 结果集是**逐节点完备**的: 被删节点下所有未被更高优先级豁免的后代键都单独在集合里.
 * 场景侧按网格归属(PartIndex.ownerOf)逐网格隐藏即可, 被保留豁免的子件不会被祖先连坐.
 *
 * 已知近似(仅退化路径): decimate_rules 不参与 —— 减面不改变"零件在不在";
 * JS RegExp 与 Python re 的方言差异 —— 现有模式全是拼音/ASCII/中文字面量, 实际无碍.
 */
import { MARKS } from './selectionModel.js'

/** 优先级分数: 显式保留 > 显式删除 > 正则保留 > 正则删除 > 尺寸阈值 */
const SCORE = {
  EXPLICIT_KEEP: 4,
  EXPLICIT_DELETE: 3,
  RULE_KEEP: 2,
  RULE_DELETE: 1,
  SIZE: 0.5,
}

/**
 * 功能: 把 prune_list.yaml 的解析结果编译成可复用的规则对象.
 * @param {object|null} config parseYaml 的结果
 * @returns {{deleteRes: RegExp[], keepRes: RegExp[], minDimensionMm: number|null}|null}
 *          规则; config 无效时返回 null(调用方退化为只算显式标记)
 */
export function compilePruneRules(config) {
  if (!config || typeof config !== 'object') return null

  const compile = (patterns) => {
    const out = []
    for (const pattern of Array.isArray(patterns) ? patterns : []) {
      try {
        out.push(new RegExp(String(pattern), 'i'))
      } catch {
        // 手写规则里的坏正则不该拖垮整个预览, 丢弃即可
      }
    }
    return out
  }

  const minDimension = Number(config.min_dimension_mm)
  return {
    deleteRes: compile(config.delete_patterns),
    keepRes: compile(config.keep_patterns),
    minDimensionMm: Number.isFinite(minDimension) && minDimension > 0 ? minDimension : null,
  }
}

/** 管线把 region_delete 的面岛分离出来时给对象名加的后缀(见 blender_clean.REGION_SPLIT_SUFFIX) */
export const REGION_SPLIT_SUFFIX = '__REGION_DELETE'

/**
 * 功能: 给一段源文本算"变没变"的戳, 与管线 03_clean_model.source_stamp 逐位一致.
 *
 * 为什么不用 SHA-256: 装配台常从局域网 IP 走 http 打开, 那不是安全上下文,
 * crypto.subtle 在那里直接是 undefined —— 用它等于让告警条永久挂着.
 * FNV-1a 只判"文件变没变", 不防篡改, 32 位加字节数前缀足够.
 *
 * @param {string} text 源文件文本(行尾须为 \n, 后端 read_text 给的就是归一后的)
 * @returns {string} 形如 "8371:1a2b3c4d"; 入参不是字符串时返回空串
 */
export function sourceStamp(text) {
  if (typeof text !== 'string') return ''
  const bytes = new TextEncoder().encode(text)
  let digest = 0x811c9dc5
  for (const byte of bytes) {
    digest = Math.imul(digest ^ byte, 0x01000193) >>> 0
  }
  return `${bytes.length}:${digest.toString(16).padStart(8, '0')}`
}

/**
 * 功能: 判断标红基线跟不跟得上当前的 prune_list.yaml.
 *
 * 形状与调用约定照 clipSchema.railCalibStatus: 判定**不致命**(基线不可用时预览退化为
 * 近似, 总比整个页面没有红色强), 但**缺戳一律不许判绿** —— 那正是这套检测要堵的漏.
 *
 * @param {object|null|undefined} baseline work/prune_preview.json 的解析结果
 * @param {string} currentStamp 当前 prune_list.yaml 原文的 sourceStamp()
 * @returns {{state: 'ok'|'stale'|'unstamped'|'missing', reason: string}} 判定
 */
export function previewStatus(baseline, currentStamp) {
  if (!baseline || typeof baseline !== 'object') {
    return { state: 'missing', reason: '没有标红基线 —— 工作台原始模型还没按当前管线重跑过' }
  }
  if (!baseline.source_stamp) {
    return { state: 'unstamped', reason: '基线没记录 prune_list.yaml 的戳, 无从判断它跟不跟得上当前规则' }
  }
  if (!currentStamp) {
    return { state: 'unstamped', reason: '算不出当前 prune_list.yaml 的戳, 无从比对' }
  }
  if (baseline.source_stamp !== currentStamp) {
    return { state: 'stale', reason: 'prune_list.yaml 改过而工作台原始模型没重跑, 基线停在改动之前' }
  }
  return { state: 'ok', reason: '' }
}

/**
 * 功能: 取 prune_list.yaml 里**规则档**的指纹(基线的裁决只依赖这几段).
 *
 * 用途是保存标记后判断基线还作不作数: 工作台保存只改 explicit_* 三段名单, 而那几段
 * 由 model.marks 实时算、基线本来就跳过 —— 若只按整份文件的戳判定, 每保存一次预览
 * 就会退化成近似一次, 而工作台的活正是反复标了又保存.
 *
 * 比的是同一个 parseYaml 在同一个运行时解析出来的两份配置, 所以直接 JSON.stringify
 * 就够(键序一致), 不涉及跨语言序列化差异.
 *
 * @param {object|null} config parseYaml 的结果
 * @returns {string} 指纹
 */
export function ruleFingerprint(config) {
  return JSON.stringify([
    config?.delete_patterns ?? null,
    config?.keep_patterns ?? null,
    config?.min_dimension_mm ?? null,
    config?.region_delete ?? null,
  ])
}

/** 节点名归一: 空白→下划线, 与管线 blender_clean._norm 同口径 */
function nameKey(name) {
  return String(name ?? '').replace(/\s/g, '_')
}

/**
 * 功能: 把基线里的"会被删"节点名展开成索引键.
 *
 * 刻意跳过 reason 为 explicit 的条目: 它们与 model.marks 同源于 prune_list.yaml 的
 * explicit_delete, 两边都采信的话, 用户取消一个标记后红色不会退 —— 得等重跑 raw
 * 才消失, 而工作台的活就是反复标了又改. 显式那一档全交给 model 实时算.
 *
 * @param {import('./PartIndex.js').PartIndex} index 零件索引
 * @param {object} baseline 基线
 * @returns {Set<string>} 索引键集合
 */
function baselineRuleDeletes(index, baseline) {
  const reasons = baseline.reasons || {}
  const wanted = new Set()
  for (const name of baseline.deleted || []) {
    if (reasons[name] === 'explicit') continue
    wanted.add(nameKey(name))
  }

  const result = new Set()
  if (!wanted.size) return result
  for (const [key, part] of index.parts) {
    // 基线写的是 Blender 对象名 = glTF 原名, 与 origName 精确对齐;
    // 再兜一手 three 消毒后的名字, 免得拿不到 origName 的模型全盘落空
    if (wanted.has(nameKey(part.origName)) || wanted.has(nameKey(part.name))) result.add(key)
  }
  return result
}

/**
 * 功能: 求当前会被管线删掉的零件键集合.
 * @param {import('./PartIndex.js').PartIndex} index 零件索引
 * @param {import('./selectionModel.js').SelectionModel} model 选择模型(显式标记来源)
 * @param {ReturnType<typeof compilePruneRules>} rules 编译后的规则; 仅退化路径用到
 * @param {object|null} [baseline] 管线产出的标红基线; 给了就以它为准, null 则退化为按规则近似
 * @returns {Set<string>} 有效删除集(索引键)
 */
export function evalEffectiveDeletes(index, model, rules, baseline = null) {
  const result = new Set()
  const deleteRes = rules?.deleteRes || []
  const keepRes = rules?.keepRes || []
  const minDim = rules?.minDimensionMm ?? null
  const baseSet = baseline ? baselineRuleDeletes(index, baseline) : null

  // 与管线 name_variants 对齐: three 名 / 中文名 / glTF 原名 / 拼音别名任一命中即算
  // (原生 GLB 的节点是中文名, prune_list 的拼音正则全靠 alias 这层命中)
  const hits = (regexes, part) => {
    for (const re of regexes) {
      if (re.test(part.name)) return true
      if (part.chinese && re.test(part.chinese)) return true
      if (part.origName && part.origName !== part.name && re.test(part.origName)) return true
      if (part.alias && re.test(part.alias)) return true
    }
    return false
  }

  const walk = (part, inheritedKeep, inheritedDelete) => {
    const mark = model.markOf(part.key)?.mark

    let keep = inheritedKeep
    if (mark === MARKS.KEEP) keep = Math.max(keep, SCORE.EXPLICIT_KEEP)

    let del = inheritedDelete
    if (mark === MARKS.DELETE) del = Math.max(del, SCORE.EXPLICIT_DELETE)

    let effectiveDelete = del
    if (baseSet) {
      // 基线已逐节点完备(管线是逐对象判的), 不必再沿子树推; 它占"正则删除"那一档,
      // 所以显式保留压得住它, 显式删除与它同向叠加
      if (baseSet.has(part.key)) effectiveDelete = Math.max(effectiveDelete, SCORE.RULE_DELETE)
    } else {
      if (keepRes.length && hits(keepRes, part)) keep = Math.max(keep, SCORE.RULE_KEEP)
      if (deleteRes.length && hits(deleteRes, part)) del = Math.max(del, SCORE.RULE_DELETE)
      // 尺寸阈值只判叶子且不下传: 大装配的包围盒不小, 碎的是散落的小实体
      effectiveDelete = del
      if (minDim !== null && part.childNames.length === 0 && part.longestMm < minDim) {
        effectiveDelete = Math.max(effectiveDelete, SCORE.SIZE)
      }
    }

    if (effectiveDelete > keep) result.add(part.key)

    for (const childKey of part.childNames) {
      const child = index.get(childKey)
      if (child) walk(child, keep, del)
    }
  }

  for (const assembly of index.assemblies) walk(assembly, 0, 0)
  return result
}
