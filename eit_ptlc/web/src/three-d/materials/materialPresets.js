/**
 * 功能: 工业材质预设库 —— 一键把选中材质(或零件覆盖)填成常见工业观感.
 *
 * 参数不是拍脑袋: 全部采自 material_semantics.yaml 里已对照实机照片调过的配方
 * (铝合金/不锈钢/玻璃/亚克力/硅胶/黄铜等), 保证预设观感与管线口径一致 ——
 * 工程师点一下预设得到的效果, 与规则命中该材质类时完全一样, 再微调即可.
 *
 * patch 只含需要覆盖的字段(sanitizePatch 口径), 应用 = OverrideModel.setMany 一步,
 * 一次撤销可整体回退.
 */

export const MATERIAL_PRESETS = [
  {
    id: 'anodized-alu',
    label: '阳极铝',
    patch: { base_color: '#C5CAD2', roughness: 0.4, metalness: 0.9 },
  },
  {
    // 颜色取整机缎面铝实例 MAT_NAT_ALUMINUM_F0F0F0 的原生直采色,
    // 不取类基色 #C5CAD2 —— 那与上面的阳极铝几乎重合, 区分不开.
    id: 'satin-alu',
    label: '缎面铝',
    patch: { base_color: '#F0F0F0', roughness: 0.35, metalness: 0.88 },
  },
  {
    id: 'stainless-brushed',
    label: '不锈钢',
    patch: { base_color: '#CCD3DB', roughness: 0.3, metalness: 0.95 },
  },
  {
    id: 'powder-coat',
    label: '喷粉钣金',
    patch: { base_color: '#B8BDC4', roughness: 0.55, metalness: 0.08 },
  },
  {
    id: 'black-anodized',
    label: '黑色阳极',
    patch: { base_color: '#2E3238', roughness: 0.45, metalness: 0.85 },
  },
  {
    id: 'glass',
    label: '玻璃',
    patch: { base_color: '#DCEAF2', roughness: 0.05, metalness: 0, transmission: 0.92, ior: 1.5 },
  },
  {
    id: 'acrylic',
    label: '亚克力/PC',
    patch: { base_color: '#DCEAF2', roughness: 0.12, metalness: 0, transmission: 0.72, ior: 1.49 },
  },
  {
    id: 'rubber',
    label: '橡胶/硅胶',
    patch: { base_color: '#2A2F38', roughness: 0.88, metalness: 0 },
  },
  {
    id: 'brass',
    label: '黄铜',
    patch: { base_color: '#B08D57', roughness: 0.35, metalness: 0.95 },
  },
  {
    id: 'white-plastic',
    label: '白色工程塑料',
    patch: { base_color: '#E8E6DF', roughness: 0.5, metalness: 0 },
  },
  {
    id: 'emissive',
    label: '发光体',
    patch: { base_color: '#F2F2F2', emission: '#FFFFFF', emission_strength: 3, roughness: 0.4, metalness: 0 },
  },
]

/**
 * 功能: 从材质名解码 CAD 量化色 —— MAT_<类>_<HEX>[_A<α档>] 的 HEX 段.
 *
 * 这是"恢复 CAD 原色"的依据: 烘焙后 GLB 的运行时 baseline 已含上一轮人工覆盖,
 * 靠它回不到 CAD 直采色; 而材质名里的量化 HEX 正是 build_materials.py 颜色直采时
 * 写死的权威记录.
 *
 * @param {string} name 材质名
 * @returns {string|null} '#RRGGBB'; 名字不含色段返回 null
 */
export function cadColorOf(name) {
  const match = /^MAT_[A-Z0-9_]*?_([0-9A-F]{6})(?:_A\d{2})?$/.exec(name || '')
  return match ? `#${match[1]}` : null
}
