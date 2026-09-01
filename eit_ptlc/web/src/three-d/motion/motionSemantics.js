/**
 * 功能: 运动语义分类 —— 把 manifest 投影成"哪些东西会动、哪些是耗材、哪些待装配"的条目表.
 *
 * 纯函数, 零 three 依赖, 可 node --test. 它是动作界面的数据地基:
 *   - 运动语义着色(MotionPaint)按 category 给三维上色;
 *   - 右侧语义列表(SemanticsPanel)按 kind 分组展示, 色点同源;
 *   - 调试卡(MovableInspector)按 kind/params 生成滑杆与点动.
 *
 * category 语义:
 *   movable        有几何且已绑定, 能被 MachineStateDriver 驱动(轴/关节/执行器/联动/工具)
 *   consumable     耗材(INV_* 账本驱动显隐: 收集器/样品瓶/玻璃板)
 *   declared-only  数据侧已声明但几何未绑定(未 rigged 轴/51 条 data-only 机构/停用的液面)
 *   (static 不出条目 —— 其余一切默认静止, 着色时兜底)
 */

/** 分类颜色: 列表色点与三维着色的单一来源 */
export const SEMANTIC_COLORS = {
  static: '#dfe3e8',
  movable: '#3f8cff',
  consumable: '#e8a13d',
  'declared-only': '#8a9098',
}

/** 分类中文名 */
export const CATEGORY_LABELS = {
  static: '静止',
  movable: '可动',
  consumable: '耗材',
  'declared-only': '待装配',
}

/** kind 分组的显示配置(顺序即面板排列顺序) */
export const KIND_GROUPS = [
  { kind: 'axis', label: '直线轴' },
  { kind: 'joint', label: '机械臂关节' },
  { kind: 'tool', label: '末端工具' },
  { kind: 'actuator', label: '执行器' },
  { kind: 'linkage', label: '联动组' },
  { kind: 'consumable', label: '耗材' },
  { kind: 'tank', label: '液面' },
  { kind: 'mechanism', label: '数据侧机构' },
]

/**
 * 功能: 把"manifest 声明可动但场景解析失败"的轴降级并打上 resolveFailed 标记.
 *
 * classifySemantics 是 manifest 的纯投影, 不知道节点是否真的解析成功; 驱动层
 * (MachineStateDriver.axes)只登记解析成功的 rigged 轴 —— 两边对不上的轴在界面上
 * "看似可动实则无高亮无驱动"(axis_3y 的 .001 后缀事故). 修复后本函数是防回归:
 * 再出现解析失败, 列表直接亮"解析失败"徽章而不是静默装死.
 *
 * @param {Array} entries classifySemantics 产物(就地修改并返回)
 * @param {Set<string>} resolvedAxisIds 驱动层实际解析成功的轴 id 集
 * @returns {Array} entries
 */
export function markAxisResolveFailures(entries, resolvedAxisIds) {
  for (const entry of entries || []) {
    if (entry.kind !== 'axis' || entry.category !== 'movable') continue
    if (resolvedAxisIds?.has(entry.params.axisId)) continue
    entry.category = 'declared-only'
    entry.resolveFailed = true
    entry.glbNodes = []
  }
  return entries
}

/**
 * 功能: 把 manifest 分类成运动语义条目.
 * @param {object} manifest device-manifest(v2)
 * @returns {Array<{id: string, kind: string, label: string, station?: string,
 *   category: string, glbNodes: string[], params: object}>} 条目数组
 */
export function classifySemantics(manifest) {
  const entries = []
  if (!manifest || typeof manifest !== 'object') return entries

  // -- 直线轴: rigged 可动, 未 rigged 待装配 -------------------------------
  for (const axis of manifest.axes || []) {
    entries.push({
      id: `axis:${axis.id}`,
      kind: 'axis',
      label: axis.label || axis.id,
      station: axis.station,
      category: axis.rigged && axis.glbNode ? 'movable' : 'declared-only',
      glbNodes: axis.rigged && axis.glbNode ? [axis.glbNode] : [],
      params: {
        axisId: axis.id,
        rangeMm: axis.rangeMm,
        sign: axis.sign,
        zeroOffsetMm: axis.zeroOffsetMm,
        axis: axis.axis,
        rigged: Boolean(axis.rigged),
      },
    })
  }

  // -- CR5 关节: 整臂随 robot.glbNode 着色, 关节逐条供点动 -----------------
  const robot = manifest.robot || {}
  if (robot.glbNode) {
    entries.push({
      id: 'robot:body',
      kind: 'joint',
      label: robot.label || '机械臂',
      station: 'ROBOT',
      category: robot.jointsRigged ? 'movable' : 'declared-only',
      glbNodes: robot.jointsRigged ? [robot.glbNode] : [],
      params: { isRobotRoot: true },
    })
  }
  for (const [index, joint] of (robot.joints || []).entries()) {
    entries.push({
      id: `joint:${joint.id}`,
      kind: 'joint',
      label: `关节 ${joint.id}`,
      station: 'ROBOT',
      category: robot.jointsRigged && joint.linkNode ? 'movable' : 'declared-only',
      // 关节强调用连杆几何; 着色已由整臂条目覆盖, 重复涂同色无害
      glbNodes: robot.jointsRigged && joint.linkNode ? [joint.linkNode] : [],
      params: { jointIndex: index, limitDeg: joint.limitDeg, sign: joint.sign },
    })
  }

  // -- 末端工具 -----------------------------------------------------------
  for (const tool of manifest.tools || []) {
    entries.push({
      id: `tool:${tool.id}`,
      kind: 'tool',
      label: tool.label || tool.id,
      station: 'TOOLING',
      category: tool.glbNode ? 'movable' : 'declared-only',
      glbNodes: tool.glbNode ? [tool.glbNode] : [],
      params: {
        toolId: tool.id,
        controllerTool: tool.controllerTool,
        dockNode: tool.dockNode,
        mountNode: tool.mountNode,
      },
    })
  }

  // -- 执行器 / 联动组 ----------------------------------------------------
  for (const actuator of manifest.actuators || []) {
    entries.push({
      id: `actuator:${actuator.id}`,
      kind: 'actuator',
      label: actuator.label || actuator.id,
      category: actuator.node ? 'movable' : 'declared-only',
      glbNodes: actuator.node ? [actuator.node] : [],
      params: {
        actuatorId: actuator.id,
        motion: actuator.motion,
        axis: actuator.axis,
        sign: actuator.sign,
        inputRange: actuator.inputRange,
        outputRange: actuator.outputRange,
        transitionS: actuator.transitionS,
      },
    })
  }
  for (const linkage of manifest.linkages || []) {
    const nodes = (linkage.members || []).map((member) => member.node).filter(Boolean)
    entries.push({
      id: `linkage:${linkage.id}`,
      kind: 'linkage',
      label: linkage.label || linkage.id,
      category: nodes.length ? 'movable' : 'declared-only',
      glbNodes: nodes,
      params: {
        linkageId: linkage.id,
        inputRange: linkage.inputRange,
        transitionS: linkage.transitionS,
        // 耦合机构(展缸盖)的成员行程被几何锁死, 面板据此只暴露主参数
        kinematics: linkage.kinematics,
        members: (linkage.members || []).map((member) => ({
          node: member.node,
          axis: member.axis,
          sign: member.sign,
          motion: member.motion,
          outputRange: member.outputRange,
          unitScale: member.unitScale,
        })),
      },
    })
  }

  // -- 耗材(账本驱动显隐, 分三组) -----------------------------------------
  const inventory = manifest.inventory || {}
  const rackNodes = (inventory.rack || []).map((slot) => slot.node).filter(Boolean)
  if (rackNodes.length) {
    entries.push({
      id: 'consumable:rack',
      kind: 'consumable',
      label: `料架耗材(${rackNodes.length} 槽)`,
      station: 'RACK',
      category: 'consumable',
      glbNodes: rackNodes,
      params: { group: 'rack' },
    })
  }
  const stagingNodes = (inventory.staging || []).map((slot) => slot.node).filter(Boolean)
  if (stagingNodes.length) {
    entries.push({
      id: 'consumable:staging',
      kind: 'consumable',
      label: `中转托盘耗材(${stagingNodes.length} 位)`,
      station: 'STAGINGA',
      category: 'consumable',
      glbNodes: stagingNodes,
      params: { group: 'staging' },
    })
  }
  const magazineNodes = (inventory.magazines || []).map((mag) => mag.node).filter(Boolean)
  if (magazineNodes.length) {
    entries.push({
      id: 'consumable:magazines',
      kind: 'consumable',
      label: `玻璃板(${magazineNodes.length} 仓)`,
      station: 'FEEDLIFT',
      category: 'consumable',
      glbNodes: magazineNodes,
      params: { group: 'magazines' },
    })
  }

  // -- 液面(现停用: liquidNode 全 null 时是 declared-only) -----------------
  for (const tank of manifest.tanks || []) {
    entries.push({
      id: `tank:${tank.id}`,
      kind: 'tank',
      label: tank.label || tank.id,
      station: 'DEVELOP',
      category: tank.liquidNode ? 'movable' : 'declared-only',
      glbNodes: tank.liquidNode ? [tank.liquidNode] : [],
      params: { tankIndex: tank.index, stateFrom: tank.stateFrom },
    })
  }

  // -- 数据侧机构(51 条 data-only + 3 条已在 actuator/linkage 出过条目) ----
  const covered = new Set(
    [...(manifest.actuators || []), ...(manifest.linkages || [])].map((item) => item.id),
  )
  for (const mech of (manifest.realtime || {}).mechanisms || []) {
    if (covered.has(mech.id)) continue
    entries.push({
      id: `mech:${mech.id}`,
      kind: 'mechanism',
      label: mech.label || mech.id,
      station: mech.station,
      category: 'declared-only',
      glbNodes: [],
      params: { mechKind: mech.kind, feedbackAvailable: mech.feedbackAvailable },
    })
  }

  return entries
}
