/**
 * 功能: 合并块成员元数据的统一服务 —— 归一两代报告格式、按块键/成员名索引、
 *       三级兜底解析块键、命中点→成员候选排序.
 *
 * 数据源是管线 03 的 join.members(dev 走授权中间件读 clean_report, 生产回退
 * 部署产物 merge-members.json). 键 = "<ST_工位>/<STATIC_块名[.00N]>";
 * 值旧格式是成员名数组, 新格式是 [{name, tris, bbox:{c,s}}](gltf-y-up, 与
 * structure.json 同口径 —— 前端用 machineRoot.children[0] 的局部坐标直接比对,
 * 严禁出现任何单位换算常量).
 *
 * 本模块不 import three, 纯数据运算, node --test 可直接跑.
 */

/**
 * 功能: 剥 Blender 重名后缀 .00N, 得到跨次运行稳定的 base 名(写盘一律用它).
 * @param {string} name 成员名
 * @returns {string} base 名
 */
export function baseName(name) {
  return String(name || '').replace(/\.\d{3}$/, '')
}

/**
 * 功能: 求零件的**实例族名** —— 剥掉 SolidWorks 装配实例后缀 `-N`.
 *
 * `侧门-1` 与 `侧门-2` 是同一个零件放了两次, 用户说"这个门板"指的是这个零件,
 * 不是其中某一个实例. 管线侧 name_variants 只剥 Blender 的 `.00N`, 两个实例是
 * 两个独立的键 —— 所以"整族一起处理"必须由这一层负责, 否则拆出只会拆掉一半.
 *
 * @param {string} name 零件/成员名
 * @returns {string} 族名(无实例后缀时即原名)
 */
export function familyName(name) {
  return baseName(name).replace(/-\d+$/, '')
}

/**
 * 功能: 归一成员条目 —— 旧报告是纯名字, 新报告是 {name, tris, bbox}.
 * @param {string|object} raw 报告里的原始条目
 * @returns {{name: string, tris: number, bbox: {c: number[], s: number[]}|null}} 归一后的成员
 */
export function normalizeMember(raw) {
  if (typeof raw === 'string') return { name: raw, tris: 0, bbox: null }
  return { name: raw?.name || '', tris: raw?.tris || 0, bbox: raw?.bbox || null }
}

/**
 * 功能: 把 join.members 建成多路索引.
 * @param {object|null} blocks 块键 -> 成员数组(两代格式均可)
 * @returns {{blocks: Map, byBase: Map, byFamily: Map}|null} blocks: 块键->Member[];
 *          byBase: 成员base名->[{blockKey, member}](Blender 去重后缀已剥);
 *          byFamily: 实例族名->同上(装配实例后缀 -N 也剥, 供整族操作)
 */
export function buildMemberIndex(blocks) {
  if (!blocks) return null
  const blockMap = new Map()
  const byBase = new Map()
  const byFamily = new Map()
  for (const [blockKey, list] of Object.entries(blocks)) {
    const members = (list || []).map(normalizeMember)
    blockMap.set(blockKey, members)
    for (const member of members) {
      const base = baseName(member.name)
      if (!base) continue
      if (!byBase.has(base)) byBase.set(base, [])
      byBase.get(base).push({ blockKey, member })
      const family = familyName(member.name)
      if (!byFamily.has(family)) byFamily.set(family, [])
      byFamily.get(family).push({ blockKey, member })
    }
  }
  return { blocks: blockMap, byBase, byFamily }
}

/**
 * 功能: 把一批成员按实例族聚合(成员清单按"零件"而非"实例"呈现的数据源).
 * @param {Array|null} members 归一成员数组
 * @returns {Array|null} [{family, members, tris}], 按三角形数降序
 */
export function groupByFamily(members) {
  if (!members) return null
  const map = new Map()
  for (const member of members) {
    const family = familyName(member.name)
    let entry = map.get(family)
    if (!entry) {
      entry = { family, members: [], tris: 0 }
      map.set(family, entry)
    }
    entry.members.push(member)
    entry.tris += member.tris || 0
  }
  return [...map.values()].sort((a, b) => b.tris - a.tris)
}

/**
 * 功能: 按块节点的多种写法解析成员清单(逐行移植自材质台 staticMembers 的三级兜底).
 *
 * 三级兜底: ①原名全路径(保留 .001 点号) ②three 消毒名全路径
 * ③块名后缀扫描 —— 跨次运行的 .001 顺序漂移时仍可命中.
 *
 * @param {{blocks: Map}|null} index buildMemberIndex 的产物
 * @param {string} stationOrig 工位根原名
 * @param {string} blockOrig 块原名
 * @param {string} stationName 工位根 three 名
 * @param {string} blockName 块 three 名
 * @returns {Array|null} 成员数组; index 缺失返回 null; 未命中返回 []
 */
export function resolveMembers(index, stationOrig, blockOrig, stationName, blockName) {
  if (!index) return null
  const exact = [`${stationOrig}/${blockOrig}`, `${stationName || ''}/${blockName}`]
  for (const key of exact) {
    const hit = index.blocks.get(key)
    if (hit) return hit
  }
  const suffix = `/${blockOrig}`
  for (const [key, list] of index.blocks) {
    if (key.endsWith(suffix)) return list
  }
  return []
}

/**
 * 功能: 读取成员元数据 —— dev 优先授权中间件的 clean_report(与本次 GLB 同次运行,
 *       最权威), 失败回退部署产物 merge-members.json, 都拿不到返回 null(消费方
 *       整体降级为"旧版产物"提示).
 * @param {{readFile: Function}|null} api 授权中间件客户端; 不可用传 null
 * @param {Function} [fetchImpl] fetch 实现(测试注入用)
 * @returns {Promise<object|null>} join.members 的 blocks 对象
 */
export async function loadMemberData(api, fetchImpl = globalThis.fetch) {
  if (api) {
    try {
      const report = JSON.parse(await api.readFile('clean_report'))
      const blocks = report?.join?.members
      if (blocks && Object.keys(blocks).length) return blocks
    } catch {
      // dev 中间件不可用/报告缺字段: 落到部署产物回退
    }
  }
  try {
    const res = await fetchImpl('/api/3d/assets/models/merge-members.json')
    if (res?.ok) {
      const data = await res.json()
      if (data?.blocks && Object.keys(data.blocks).length) return data.blocks
    }
  } catch {
    // 部署产物也没有(老部署): 返回 null
  }
  return null
}

/**
 * 功能: 命中点→成员候选排序(CAD "Select Other" 惯例).
 *
 * 规则: 包围盒含命中点者优先, 其中小体积在前(点在门板上的把手区域时, 把手排在
 * 门板前面); 不含点者按逐轴超出量升序补位(吸收 04 量化/焊接的毫米级漂移).
 * 无 bbox 的成员(旧报告)不参与候选.
 *
 * 单位: 场景经 normalize_units 后是**米**制(structure.json 的 size 可佐证),
 * bbox 与命中点同口径, 容差默认 0.002(=2mm) —— 别按毫米直觉写大数.
 *
 * @param {Array} members 归一后的成员数组
 * @param {number[]} point 命中点(glTF y-up 模型空间, 与 bbox 同口径)
 * @param {{limit?: number, tol?: number}} [opts] limit=候选数上限; tol=含点判定容差(米)
 * @returns {{list: Array, total: number, containCount: number}} 候选清单与统计
 */
export function rankCandidates(members, point, { limit = 5, tol = 0.002 } = {}) {
  const scored = []
  for (const member of members || []) {
    const box = member.bbox
    if (!box || !Array.isArray(box.c) || !Array.isArray(box.s)) continue
    let overflow = 0
    for (let axis = 0; axis < 3; axis += 1) {
      const d = Math.abs(point[axis] - box.c[axis]) - (box.s[axis] / 2 + tol)
      if (d > overflow) overflow = d
    }
    const volume =
      Math.max(box.s[0], 1e-6) * Math.max(box.s[1], 1e-6) * Math.max(box.s[2], 1e-6)
    scored.push({ member, contains: overflow <= 0, overflow, volume })
  }
  scored.sort((a, b) => {
    if (a.contains !== b.contains) return a.contains ? -1 : 1
    if (a.contains) return a.volume - b.volume
    return a.overflow - b.overflow
  })
  return {
    list: scored.slice(0, limit).map((entry) => entry.member),
    total: (members || []).length,
    containCount: scored.filter((entry) => entry.contains).length,
  }
}
