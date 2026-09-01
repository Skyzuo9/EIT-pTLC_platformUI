/**
 * 功能: 把材质工作台调出来的观感参数写回 material_semantics.yaml, 且**保留原文件注释**.
 *
 * 与工作台的 yamlPatch 同一策略: 只拥有自己的段落, 每次写回整段重建;
 * 文件里其余段落(rules / native_materials / 各种踩坑说明注释)一个字都不碰.
 * 边界清晰, 人和机器互不覆盖.
 *
 * 四个段落:
 *   appearance_overrides —— 键=材质名(MAT_*), 整类零件一起变
 *   part_overrides       —— 键=零件节点名, 单个零件强制独立材质(MAT_PART_<slug>)
 *   part_isolate         —— 零件名列表, 只脱离静态合并不改观感(MAT_SOLO_<slug>)
 *   part_groups          —— 组名 -> {parts, 参数}, 决定哪些零件合并在一起
 */
import { Document, parseDocument } from 'yaml'

/**
 * 功能: 生成"拥有一个 YAML 段落"的 patch/read 函数对.
 *
 * @param {string} key 段落键名
 * @param {string} comment 段落上方的说明注释
 * @returns {{patch: Function, read: Function}} 函数对
 */
function makeSectionPatcher(key, comment) {
  return {
    /**
     * 功能: 把覆盖模型写回 YAML 原文(整段重建, 其余不动).
     * @param {string} originalText 原始 YAML 文本
     * @param {import('./overrideModel.js').OverrideModel} model 覆盖模型
     * @returns {string} 新的 YAML 文本
     */
    patch(originalText, model) {
      const doc = originalText ? parseDocument(originalText) : new Document({})
      const section = model.toSection()

      doc.delete(key)

      // 必须先 createNode 再挂注释: 直接 doc.set(key, 普通对象) 存进去的仍是那个 JS 对象,
      // 往它身上写 commentBefore 会变成一个真实的键, 序列化后 YAML 里就多出一行垃圾数据.
      const node = doc.createNode(section)
      node.commentBefore = comment
      // 即使为空也要写一个空映射: 留着这个键, 下次打开文件的人才知道有这么个机制
      doc.set(key, node)

      return doc.toString({ lineWidth: 0 })
    },
    /**
     * 功能: 从 YAML 原文里取出该段.
     * @param {string} text YAML 文本
     * @returns {object} 段内容; 不存在返回空对象
     */
    read(text) {
      if (!text) return {}
      try {
        const doc = parseDocument(text)
        return doc.toJS()?.[key] || {}
      } catch {
        return {}
      }
    },
  }
}

const appearance = makeSectionPatcher(
  'appearance_overrides',
  ' 人工覆盖: 材质名 -> 观感参数. **优先级最高, 压过下面所有规则.**\n' +
    ' 本段由「材质工作台」(/3d/materials)写回, 每次保存整段重建; 手改也可以, 但会被下次保存覆盖.\n' +
    ' 键是最终材质名, 与它由哪条规则产生无关 —— rules / native_materials / 颜色直采 调法一样.\n' +
    ' 只列想改的字段即可, 未列出的沿用原规则的值.',
)

const parts = makeSectionPatcher(
  'part_overrides',
  ' 零件级覆盖: 零件节点名 -> 观感参数(与 appearance_overrides 同一套字段).\n' +
    ' 本段由「材质工作台」写回, 每次保存整段重建. 键可写 glTF 原名(中文)或拼音 slug,\n' +
    ' 管线按 name_variants 双写法 + 空白消毒 + 47 字符截断匹配.\n' +
    ' 效果: 命中零件以其当前材质为底叠加补丁, 强制生成专属实例 MAT_PART_<slug> ——\n' +
    ' 该零件因此脱离共享材质, 重跑一次后在合并模型里单独成块, 永久可实时预览.\n' +
    ' 注意: 每条覆盖约 +1 绘制调用(05_report 有 500 上限门禁), 不宜超过几十条.',
)

const isolate = makeSectionPatcher(
  'part_isolate',
  ' 孤立清单: 零件原名列表(剥 .00N 后缀的 base 名), 语义="只脱离静态合并、不改观感".\n' +
    ' 本段由「材质工作台」的"拆出为独立零件"写回, 每次保存整段重建.\n' +
    ' 效果: 命中零件以当前材质为底生成专属实例 MAT_SOLO_<slug>(观感不变), 合并时因\n' +
    ' 材质名唯一而独立成块; 同名多实例会一并孤立. 要改观感请改用 part_overrides ——\n' +
    ' 两段互斥, 重叠键在 build_materials 清洗期丢弃孤立标记并告警.\n' +
    ' 备注: 04 优化的材质去重会把"参数与类完全相同"的 MAT_SOLO 名折叠回类名,\n' +
    ' 不影响独立性(几何拆分已在 Blender 侧烘定, 每次重跑都会重演).\n' +
    ' 注意: 每条约 +1 绘制调用(05_report 有 500 上限门禁), 不宜超过几十条.',
)

const groups = makeSectionPatcher(
  'part_groups',
  ' 材质组: 组名 -> { parts: [零件原名...], 观感字段子集 }.\n' +
    ' 组内成员共享一个专属材质实例 MAT_GROUP_<slug>(底=parts 首个成员的类材质 ⊕ 组参数),\n' +
    ' 重跑后按工位合并为同一 STATIC 块 —— 这就是"哪些零件合并在一起"的决定权.\n' +
    ' 生效叠加序: 材质类 < 材质组 < 单件覆盖(part_overrides). 一零件至多属一组.\n' +
    ' 本段由「材质工作台」写回, 每次保存整段重建.',
)

/** 材质类覆盖段(appearance_overrides)的写回与读取 */
export const patchAppearanceOverrides = appearance.patch
export const readAppearanceOverrides = appearance.read

/** 零件级覆盖段(part_overrides)的写回与读取 */
export const patchPartOverrides = parts.patch
export const readPartOverrides = parts.read

/** 孤立清单段(part_isolate)的写回与读取 */
export const patchPartIsolate = isolate.patch
export const readPartIsolate = isolate.read

/** 材质组段(part_groups)的写回与读取 */
export const patchPartGroups = groups.patch
export const readPartGroups = groups.read
