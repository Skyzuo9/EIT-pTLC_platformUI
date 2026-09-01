/**
 * 功能: 把工作台的授权结果写回 YAML, 且**保留原文件的注释与既有结构**.
 *
 * 为什么不能简单地 parse → 改 → stringify: prune_list.yaml / rig_map.yaml 里
 * 大量注释解释了"这条规则为什么存在"(踩过的坑、现场核对结论), 那些注释比规则本身
 * 更值钱. 用 yaml 库的 Document API 做原地修改, 注释与键序都能原样保留.
 *
 * 授权段落采用"整段替换"策略: 工作台只拥有 explicit_* 这几个段, 每次写回时整段重建;
 * 手写的正则规则段一个字都不碰. 边界清晰, 人和机器互不覆盖.
 */
import { Document, parseDocument } from 'yaml'

/** 工作台拥有的段落; 其余段落一律不动 */
const OWNED_PRUNE_KEYS = ['explicit_delete', 'explicit_keep', 'explicit_decimate']

/** 段落上方的说明注释, 让下次打开文件的人知道这段是怎么来的 */
const OWNED_COMMENT =
  ' 以下 explicit_* 段由「装配工作台」点选生成, 每次写回整段重建.\n' +
  ' 优先级高于上面的正则规则: 显式保留 > 显式删除 > 正则删减.\n' +
  ' 手工编辑也可以, 但下次在工作台里点选保存会覆盖整段.'

/**
 * 功能: 把索引键还原成 GLB 里的原始节点名.
 *
 * 索引为了保证唯一性给同名节点加了 `#2` 这样的后缀, 但管线侧是按原始名匹配的,
 * 而且"删掉这个型号的螺栓"本来就该对全部同名实例生效, 所以写回时一律去掉后缀。
 *
 * @param {string} key 索引键
 * @returns {string} 原始节点名
 */
function baseName(key) {
  const index = key.indexOf('#')
  return index > 0 ? key.slice(0, index) : key
}

/**
 * 功能: 去重并排序 —— 保证写出的 YAML 稳定可 diff.
 * @param {string[]} names 名称数组
 * @param {(name: string) => string} [toSavedName] 写盘前的名字翻译(three 名 → glTF 原名)
 * @returns {string[]} 结果
 */
function normalize(names, toSavedName = (name) => name) {
  return [...new Set(names.map((key) => toSavedName(baseName(key))))].sort()
}

/**
 * 功能: 把选择模型的标记写回 prune_list.yaml 的原文.
 *
 * toSavedName 的意义: three.js 加载时会消毒节点名(空格→下划线等), 而管线/Blender 侧
 * 用的是 glTF **原名** —— 名单必须写原名才能命中(硬约束 27). 翻译函数由调用方从
 * PartIndex 提供; 不传则原样写(单测与降级路径).
 *
 * @param {string} originalText 原始 YAML 文本
 * @param {import('./selectionModel.js').SelectionModel} model 选择模型
 * @param {(name: string) => string} [toSavedName] 名字翻译
 * @returns {string} 新的 YAML 文本
 */
export function patchPruneList(originalText, model, toSavedName = (name) => name) {
  const doc = originalText ? parseDocument(originalText) : new Document({})

  const deletes = normalize(model.namesWithMark('delete'), toSavedName)
  const keeps = normalize(model.namesWithMark('keep'), toSavedName)

  // 同名实例被标了不同比例时取最激进的那个 —— 它们在管线里是同一族, 只能有一个比例
  const decimateMap = new Map()
  for (const [key, value] of model.marks) {
    if (value.mark !== 'decimate') continue
    const name = toSavedName(baseName(key))
    const ratio = value.ratio ?? 0.3
    decimateMap.set(name, Math.min(decimateMap.get(name) ?? 1, ratio))
  }
  const decimates = [...decimateMap.entries()]
    .map(([name, ratio]) => ({ name, ratio }))
    .sort((a, b) => a.name.localeCompare(b.name))

  // 先清掉旧的授权段, 再按当前状态重建 —— 避免"删了标记但 yaml 里还留着"
  for (const key of OWNED_PRUNE_KEYS) doc.delete(key)

  if (deletes.length) doc.set('explicit_delete', deletes)
  if (keeps.length) doc.set('explicit_keep', keeps)
  if (decimates.length) doc.set('explicit_decimate', decimates)

  // 给第一个存在的授权段挂上说明注释
  for (const key of OWNED_PRUNE_KEYS) {
    const node = doc.get(key, true)
    if (node) {
      node.commentBefore = OWNED_COMMENT
      break
    }
  }

  return doc.toString({ lineWidth: 0 })
}

// 早期的 patchRigMapAxes 已删除: 它写 `carriage_nodes`(裸字符串数组), 而管线契约
// (blender_clean.py::build_axis_carriages)读的是 `carriage_members`(匹配器对象数组
// {equals|contains, expect_count}), 从未接线也从未生效. 正确实现见 motion/rigPatch.js
// 的 patchRigMapCarriage —— 装配台的"指认滑块成员"模式(?assign=<axisId>)调它.

/**
 * 功能: 把机器人关节链写回 rig_map.yaml 的 robot 段.
 *
 * @param {string} originalText 原始 YAML 文本
 * @param {Array<{index: number, nodes: string[], axis: number[], origin: number[]}>} joints
 *        6 个关节, index 从 1 开始
 * @returns {string} 新的 YAML 文本
 */
export function patchRigMapRobot(originalText, joints) {
  const doc = parseDocument(originalText)
  const robot = doc.get('robot', true)
  if (!robot) throw new Error('rig_map.yaml 里找不到 robot 段')

  robot.set(
    'joints',
    joints
      .slice()
      .sort((a, b) => a.index - b.index)
      .map((joint) => ({
        index: joint.index,
        name: `J${joint.index}`,
        nodes: [...joint.nodes].sort(),
        axis: joint.axis.map((v) => Number(v.toFixed(4))),
        origin: joint.origin.map((v) => Number(v.toFixed(4))),
      })),
  )
  robot.set('joints_rigged', joints.length === 6)
  robot.set('assigned_by', 'workbench')

  return doc.toString({ lineWidth: 0 })
}

/**
 * 功能: 把工位归属修正写回 rig_map.yaml.
 *
 * 写的是 explicit 名单而不是改正则: 正则是通用规则, explicit 是个案纠正, 两者并存,
 * explicit 优先。这样新图纸导出后通用规则仍然生效, 纠正也不丢。
 *
 * @param {string} originalText 原始 YAML 文本
 * @param {Record<string, string[]>} byStation 工位 id -> 显式归属的节点名数组
 * @returns {string} 新的 YAML 文本
 */
export function patchRigMapStations(originalText, byStation) {
  const doc = parseDocument(originalText)
  const stations = doc.get('stations', true)
  if (!stations || !stations.items) {
    throw new Error('rig_map.yaml 里找不到 stations 段')
  }

  for (const item of stations.items) {
    const id = item.get?.('id')
    const names = byStation[id]
    if (names && names.length) item.set('explicit', [...names].sort())
    else item.delete?.('explicit')
  }

  return doc.toString({ lineWidth: 0 })
}

/**
 * 功能: 解析 YAML 文本为普通对象(读取既有配置时用).
 * @param {string} text YAML 文本
 * @returns {object} 解析结果; 空文本返回空对象
 */
export function parseYaml(text) {
  if (!text || !text.trim()) return {}
  return parseDocument(text).toJS() || {}
}
