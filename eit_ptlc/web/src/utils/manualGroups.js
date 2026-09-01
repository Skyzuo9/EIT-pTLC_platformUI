// 单点点表的纯展示分组 (无 Vue 依赖, 进 node --test)
//
// 为什么在前端分组而不是 manual_points.yaml 加 group 字段: /api/manual/points 的序列化
// 是双层显式白名单 (config/loader.py 逐字段提取进 frozen dataclass, controller/manual_service.py
// points() 再手工挑字段), 透传新字段要动 3 个后端文件; 而分组是纯展示关切, id/label 本就是
// 点表的渲染契约 (yaml 头注: 工位归组用于设备节点页的面板分栏), 启发式在前端一处纯函数闭环。

// 分类顺序即展示顺序: 有传感反馈的动作机构 (气缸) 在前, 纯命令态设备 (阀/泵/电机) 靠后,
// 机械臂末端 (夹爪/旋转/真空) 再靠后 —— 它们只在三维手动面板出现, 2D 设备节点页永远空组被剔
const GROUP_ORDER = ['cylinder', 'valve', 'pump', 'motor', 'gripper', 'rotary', 'vacuum', 'other']
const GROUP_TITLES = {
  cylinder: '气缸',
  valve: '电磁阀',
  pump: '泵',
  motor: '电机',
  gripper: '夹爪',
  rotary: '旋转',
  vacuum: '真空',
  other: '其他执行器',
}

/**
 * 功能:
 *     按 label 关键字给执行器分类 (现有 51 条全部命中前四类; 新条目落 other, 永不丢失)
 * 参数:
 *     c 对象, /api/manual/points 的 cylinder 条目 ({id, label, ...})
 * 返回:
 *     str, 'cylinder' | 'valve' | 'pump' | 'motor' | 'other'
 */
export function classifyCylinder(c) {
  const label = (c && c.label) || ''
  // 判序有讲究: "真空阀"含"阀"须先于泵/电机; "大真空泵"不含"阀"落泵; 定位气缸最后兜"气缸"
  if (label.includes('阀')) return 'valve'
  if (label.includes('泵')) return 'pump'
  if (label.includes('电机')) return 'motor'
  if (label.includes('气缸')) return 'cylinder'
  return 'other'
}

/**
 * 功能:
 *     给三维 manifest 的机构条目分类 —— label 优先, 判不出才回落到条目自带的 kind。
 *
 *     为什么不直接信 kind: manifest 的 kind 由 gen_twin_manifest.py 的关键字启发式写入,
 *     它把 "电机" 与 "阀" 并进同一分支, 于是 ps_motor/刮板拍照无刷电机 在 manifest 里
 *     被标成 valve。label 这套判序 (本文件 classifyCylinder) 判得对且有测试锁, 故以它为准;
 *     机械臂末端 (吸盘翻转/96孔板夹爪/样品瓶电爪/吸盘真空) label 不含任何关键字,
 *     正好落 other 再回落到 manifest 的 rotary/gripper/vacuum —— 无需硬编码末端白名单。
 * 参数:
 *     row 对象, manifest.realtime.mechanisms 条目 ({id, label, kind, ...})
 * 返回:
 *     str, GROUP_ORDER 中的某一项
 */
export function classifyMechanism(row) {
  const byLabel = classifyCylinder(row)
  if (byLabel !== 'other') return byLabel
  const kind = row && row.kind
  return GROUP_ORDER.includes(kind) ? kind : 'other'
}

/**
 * 功能:
 *     把执行器清单按类型分成有序组 (空组不出)
 * 参数:
 *     cylinders 数组, cylinder 条目列表 (可为空/undefined)
 *     classify 函数, 可选分类器 (默认 classifyCylinder; 三维面板传 classifyMechanism)
 * 返回:
 *     数组, [{key, title, items}] 按 GROUP_ORDER 排序
 */
export function buildGroups(cylinders, classify = classifyCylinder) {
  const buckets = new Map()
  for (const c of cylinders || []) {
    const key = classify(c)
    if (!buckets.has(key)) buckets.set(key, [])
    buckets.get(key).push(c)
  }
  return GROUP_ORDER
    .filter((key) => buckets.has(key))
    .map((key) => ({ key, title: GROUP_TITLES[key], items: buckets.get(key) }))
}

// develop 32 条 id 规整为 dev_t{1|2}_{cyl|fill|drain|blow}{1-4} → 缸位×功能矩阵
const DEV_ID_RE = /^dev_t([12])_(cyl|fill|drain|blow)([1-4])$/

/**
 * 功能:
 *     把 develop 工位执行器解析成 展缸×缸位×功能 矩阵。
 *     任一条目不匹配 / 缺格 / 重复 → 返回 null, 面板整体回退通用分组路径 (不半渲染):
 *     id 契约来自 PLC 点表, 结构变了宁可退保守形态也不静默丢设备。
 * 参数:
 *     cylinders 数组, cylinder 条目列表
 * 返回:
 *     对象 {tanks: [{tank, rows: [{idx, cyl, fill, drain, blow}]}]} 或 null
 */
export function buildDevelopMatrix(cylinders) {
  const list = cylinders || []
  if (!list.length) return null
  const tanks = new Map()
  for (const c of list) {
    const m = DEV_ID_RE.exec(c.id || '')
    if (!m) return null
    const [, tank, kind, idx] = m
    if (!tanks.has(tank)) {
      tanks.set(tank, [1, 2, 3, 4].map((i) => ({ idx: i })))
    }
    const row = tanks.get(tank)[Number(idx) - 1]
    if (row[kind]) return null
    row[kind] = c
  }
  for (const rows of tanks.values()) {
    for (const row of rows) {
      if (!row.cyl || !row.fill || !row.drain || !row.blow) return null
    }
  }
  return {
    tanks: [...tanks.entries()]
      .sort(([a], [b]) => Number(a) - Number(b))
      .map(([tank, rows]) => ({ tank: Number(tank), rows })),
  }
}

/**
 * 功能:
 *     轴 id → 药丸短名 (axis_8y → "8Y"); 不匹配时原样回退
 * 参数:
 *     id 字符串, 轴 id
 * 返回:
 *     str, 短名
 */
export function axisShortName(id) {
  const m = /^axis_(\d+)([a-z])$/.exec(id || '')
  return m ? `${m[1]}${m[2].toUpperCase()}` : (id || '')
}
