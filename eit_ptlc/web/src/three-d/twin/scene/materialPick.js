/**
 * 功能: 物料实体拾取的纯逻辑层 (不 import three, node --test 可测).
 *
 * 与 MaterialPickController 的分工: 控制器只做 three 侧接线 (Raycaster/事件/索引遍历),
 * 命中裁决 (可见性守卫 / 祖先反查 / 最近孔吸附 / 菜单时刻身份补全) 全在这里 ——
 * 这四条恰是历史上踩过坑的地方, 必须能离线锁行为。
 */

/** 空孔吸附阈值(米): 一个孔距的量级 (孔网格 47.5x45mm), 超出算点在托盘本体上 */
export const HOLE_SNAP_MAX_DIST_M = 0.045

/**
 * 功能: 判断对象在场景里是否真正可见 (自身与全部祖先都 visible).
 *
 * three 的 Raycaster 根本不检查 visible —— 空孔位的耗材件 visible=false 仍会被
 * 射线命中, 不滤会出现"点到看不见的瓶子" (WorkbenchScene._isShown 同款守卫)。
 * @param {object} object 形如 {visible, parent} 的对象 (three Object3D 或测试替身)
 * @param {object|null} [root] 上溯终点 (含); 缺省走到根
 * @returns {boolean} 是否可见
 */
export function isShownUpTo(object, root = null) {
  for (let node = object; node; node = node.parent) {
    if (node.visible === false) return false
    if (root !== null && node === root) break
  }
  return true
}

/**
 * 功能: 把命中网格反查成物料身份 (沿父链上溯, 最近的登记者胜出).
 *
 * 索引按 mesh 登记时本函数等价于 Map.get; 父链上溯是对"命中了未登记的子网格"
 * (如粉桶 Group 里后来新增的网格) 的兜底 —— item 节点比 tray 节点深, 天然优先。
 * @param {object} hitObject 命中的网格
 * @param {Map<object, object>} ownerByMesh mesh/节点 -> 身份
 * @returns {object|null} 身份或 null
 */
export function resolveHit(hitObject, ownerByMesh) {
  for (let node = hitObject; node; node = node.parent) {
    const owner = ownerByMesh.get(node)
    if (owner) return owner
  }
  return null
}

/**
 * 功能: 托盘局部系里找命中点最近的孔 (空孔拾取: 空孔位无可见实体, 点托盘本体反查).
 *
 * ⚠ holeOffsets 必须是建索引时缓存的 item **home 局部位** —— 单件在途时节点已挂去
 * TOOL_MOUNT, 现取位置会把空孔判给邻孔。
 * @param {{x:number, y:number, z:number}} localPoint 命中点在托盘局部系的坐标
 * @param {Array<{hole:number, x:number, y:number, z:number}>} holeOffsets 孔位 home 局部位
 * @param {number} [maxDist] 吸附阈值(米)
 * @returns {{hole:number, dist:number}|null} 最近孔; 超阈值返回 null
 */
export function nearestHole(localPoint, holeOffsets, maxDist = HOLE_SNAP_MAX_DIST_M) {
  let best = null
  for (const offset of holeOffsets || []) {
    const dx = localPoint.x - offset.x
    const dy = localPoint.y - offset.y
    const dz = localPoint.z - offset.z
    const dist = Math.sqrt(dx * dx + dy * dy + dz * dz)
    if (best === null || dist < best.dist) best = { hole: offset.hole, dist }
  }
  if (best === null || best.dist > maxDist) return null
  return best
}

/**
 * 功能: 裁决 (kind, plate) 此刻画在货架还是中转区 —— 面板选孔反向定位三维实体用.
 *
 * 镜像 TwinBindings._updateMaterials 的显示裁决: 该板号被搬到对应中转区时, 实体画在
 * 中转托盘的 item 上, 货架托盘整棵隐藏; 否则画在货架。在途(爪上)时两边都不画,
 * 返回 null —— 调用方无可描边目标, 面板高亮自己承担反馈。
 * @param {string} kind 耗材种类 collector|bottle
 * @param {number} plate 板号
 * @param {object|null} snapshot MaterialStateStore 快照
 * @returns {{site: 'rack'|'staging', area: string|null}|null} 显示位置; 在途/未知为 null
 */
export function cellDisplaySite(kind, plate, snapshot) {
  if (!kind || plate == null) return null
  const area = kind === 'collector' ? 'staging-a' : 'staging-b'
  const staged = snapshot?.staging?.[area]?.plate
  if (staged != null && Number(staged) === Number(plate)) return { site: 'staging', area }
  for (const row of Object.values(snapshot?.transit || {})) {
    if (row.payload === 'tray' && row.kind === kind && Number(row.plate) === Number(plate)) {
      return null
    }
  }
  return { site: 'rack', area: null }
}

/**
 * 功能: 菜单弹出时刻的身份补全 —— 一切流动信息从**当前快照**现取, 不用建索引时的缓存.
 *
 * 补全内容:
 *   plate      中转托盘的板号是流动的 (建索引时恒 null), 从 snapshot.staging 现取;
 *   cell       该孔的账本行 (state/sample_id/粉液量);
 *   transitCarrier  该件/该板此刻记为在哪把爪上 (整板在途覆盖其 6 件);
 *   seatedAt   单件此刻记为停在哪个工位座上;
 *   magazineRow / stagingPlate  板仓与中转的现行账面。
 * @param {object} identity 建索引时的静态身份 {type, loc, kind, plate, area, hole, magazine}
 * @param {object|null} snapshot MaterialStateStore 快照 (cells/staging/transit/payloadSeats/magazines)
 * @returns {object} 补全后的信息对象 (原身份字段保留)
 */
export function identityAtMenuTime(identity, snapshot) {
  const info = { ...identity, cell: null, transitCarrier: null, transitStale: false,
                 seatedAt: null, stagingPlate: null, magazineRow: null }
  if (!snapshot) return info
  // 中转托盘的板号现取 (建索引时为 null 是约定, 见 TrayBinding 同款处理)
  if (identity.loc === 'staging' && identity.area) {
    const row = (snapshot.staging || {})[identity.area]
    info.stagingPlate = row?.plate ?? null
    if (info.plate == null) info.plate = info.stagingPlate
  }
  if (identity.type === 'magazine') {
    info.magazineRow = (snapshot.magazines || [])
      .find((row) => row.magazine === identity.magazine) || null
    return info
  }
  const plate = info.plate
  if (identity.kind && plate != null) {
    if (identity.hole != null) {
      info.cell = (snapshot.cells || []).find(
        (cell) => cell.kind === identity.kind && cell.plate === plate
          && cell.hole === identity.hole) || null
      info.seatedAt = (snapshot.payloadSeats || []).find(
        (row) => row.kind === identity.kind && row.plate === plate
          && row.hole === identity.hole) || null
    }
    for (const row of Object.values(snapshot.transit || {})) {
      const samePlate = row.kind === identity.kind && row.plate === plate
      if (!samePlate) continue
      // 整板在途覆盖其 6 件; 单件在途只覆盖同孔
      if (row.payload === 'tray' || (identity.hole != null && row.hole === identity.hole)) {
        info.transitCarrier = row.carrier
        info.transitStale = !!row.stale
        break
      }
    }
  }
  return info
}
