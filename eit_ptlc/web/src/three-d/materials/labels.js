/**
 * 功能: 材质与工位的中文显示名.
 *
 * 材质名(MAT_*)与工位名(ST_*)是管线的机器标识, 直接摆在界面上不好读.
 * 中文名的权威来源是 pipeline/material_semantics.yaml 各规则的 `label` 字段与
 * pipeline/rig_map.yaml 各工位的 `label` 字段 —— 这里是它们的静态抄本.
 * 改那两个 YAML 时记得同步这里(条目少, 变动罕见, 不值得为此做运行时解析).
 */

/** 材质 id -> 中文名(抄自 material_semantics.yaml 的 label) */
export const MATERIAL_LABELS = {
  // rules 段(按零件名/CAD 材质名; 前四条是 materials.yaml 里的角色规则)
  MAT_STEEL_PLATE: '钣金/钢板',
  MAT_COVER: '外罩门板',
  MAT_CYLINDER: '气缸',
  MAT_BLACK_MODULE: '黑色模块(模组端块/电机/拖链)',
  MAT_LINEAR_MODULE: '直线模组外壳',
  MAT_MODULE_TOP: '模组亮面盖板',
  MAT_GUIDE_RAIL: '直线导轨',
  MAT_GUIDE_BLOCK: '导轨滑块',
  MAT_MODULE_ACCESSORY: '模组附件',
  MAT_ALUMINUM: '铝合金',
  MAT_EXTRUSION: '铝型材',
  MAT_STAINLESS: '不锈钢',
  MAT_STEEL: '碳钢/合金钢',
  MAT_GLASS: '玻璃/石英',
  MAT_ACRYLIC: '亚克力/透明塑料',
  MAT_PEEK: 'PEEK/PTFE 工程塑料',
  MAT_PLASTIC: '通用塑料',
  MAT_URETHANE: '优力胶/聚氨酯',
  MAT_SILICONE: '硅胶/橡胶',
  MAT_COPPER: '铜/黄铜',
  MAT_TITANIUM: '钛合金',
  // native_materials 段(SolidWorks 原生外观名)
  MAT_NAT_ALUMINUM: '缎面铝',
  MAT_NAT_ALU_COAT: '铝喷粉(外罩)',
  MAT_NAT_POLISHED_STEEL: '抛光钢',
  MAT_NAT_MATTE_STEEL: '哑光钢/铸铁',
  MAT_NAT_BLACK_PAINT: '黑喷漆',
  MAT_NAT_GOLD: '哑光金/黄铜',
  MAT_NAT_RUBBER: '橡胶',
  MAT_NAT_PLASTIC: '塑料/陶瓷',
  MAT_NAT_WHITE: '白色件',
  // functional_overrides 段(功能压过材料)
  MAT_STATUS_LIGHT: '状态灯(三色灯)',
  MAT_UV_LAMP: '紫外光源',
  MAT_LIQUID: '展缸液面',
  MAT_TANK: '平面展缸',
  MAT_ROBOT: '机械臂本体',
  // 两轴算法新增的类(2026-07-31)
  MAT_ROBOT_BODY: '机械臂壳体',
  MAT_ROBOT_COVER: '机械臂端盖',
  MAT_ROBOT_TRIM: '机械臂关节环',
  MAT_ROBOT_ARM: '机械臂大臂',
  MAT_ROBOT_BASE: '机械臂底座',
  MAT_ROBOT_WRIST: '机械臂腕端',
  MAT_ROBOT_QUICKCHANGE: '机器人快换/末端法兰',
  MAT_TRAY_ROD: '托盘导柱',
  MAT_TRAY_PLATE: '托盘层板',
  MAT_LIGHT_POLE: '三色灯立柱',
  MAT_CADGLASS: '透明件',
  // 专项配方(functional_overrides 里按截图订错新增的类)
  MAT_SAMPLE_VIAL: '样品瓶玻璃',
  MAT_POWDER_BUCKET: '粉桶白塑料',
  MAT_LABWARE_PP: '实验耗材聚丙烯',
  // 兜底
  MAT_DEFAULT: '未指定材质',
}

/** 工位 id(ST_ 前缀后的部分) -> 中文名(抄自 rig_map.yaml 的 label) */
export const STATION_LABELS = {
  FRAME: '机架与外罩',
  RAIL: '地轨',
  ROBOT: '机械臂',
  DEVELOP: '展开工位',
  SAMPLING: '上样工位',
  PHOTOSCRAPE: '拍照刮板工位',
  COLLECT: '收集工位',
  FEEDLIFT: '上下料位',
  STAGINGA: '中转托盘位',
  PUMP: '泵站',
  RACK: '料架',
  TOOLING: '工具站',
}

/**
 * 功能: 取材质的中文显示名; 静态表没有的按命名规律推, 再兜底回原名.
 * @param {string} name 材质名(MAT_*)
 * @returns {string} 中文显示名
 */
export function labelOf(name) {
  if (!name) return '(无材质)'
  const known = MATERIAL_LABELS[name]
  if (known) return known

  // 零件级覆盖生成的专属实例: MAT_PART_<slug> —— 标成"零件专属"让来源一目了然
  const part = name.match(/^MAT_PART_(.+)$/)
  if (part) return `零件专属 · ${part[1]}`

  // 拆出(part_isolate)生成的专属实例: MAT_SOLO_<slug> —— 观感与原类相同, 只为独立
  const solo = name.match(/^MAT_SOLO_(.+)$/)
  if (solo) return `拆出专属 · ${solo[1]}`

  // 材质组生成的专属实例: MAT_GROUP_<slug>
  const group = name.match(/^MAT_GROUP_(.+)$/)
  if (group) return `材质组 · ${group[1]}`

  // 两轴算法的实例名: MAT_<类>_<HEX>[_Axx] —— 类出中文, 颜色/透明度带在后面
  const inst = name.match(/^(MAT_[A-Z0-9_]+?)_([0-9A-F]{6})(?:_A(\d{2,3}))?$/i)
  if (inst) {
    const cls = MATERIAL_LABELS[inst[1]] || inst[1]
    const alpha = inst[3] ? ` α${(Number(inst[3]) / 100).toFixed(2)}` : ''
    return `${cls} #${inst[2].toUpperCase()}${alpha}`
  }

  // 旧命名兼容: MAT_CAD_GLASS_040 表示 α=0.40
  const glass = name.match(/^MAT_CAD_GLASS_(\d{3})$/)
  if (glass) return `透明件 α${(Number(glass[1]) / 100).toFixed(2)}`

  return name
}

/**
 * 功能: 取工位节点名(ST_XXX)的中文显示名.
 * @param {string} nodeName 工位根节点名
 * @returns {string} 中文显示名
 */
export function stationLabelOf(nodeName) {
  const key = String(nodeName || '').replace(/^ST_/, '')
  return STATION_LABELS[key] || nodeName || '其他'
}
