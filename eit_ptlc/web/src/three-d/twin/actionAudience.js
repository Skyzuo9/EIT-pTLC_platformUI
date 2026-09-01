/**
 * 功能: 把 93 个原子动作分成"运维日常"与"工程师专用"两类.
 *
 * 背景: 动作声明 (config/actions/**\/*.yaml) 里**没有任何危险分级** —— 唯一的门是
 * `modes: [DEBUG]` 这一个二值量, 它管的是"调试模式才能发", 不是"这动作该不该给操作员看"。
 * 于是工位面板过去把 21 条 robot.* 一股脑铺出来, 里头既有 robot.query (只读) 也有
 * robot.set_do (裸 DO 直控)。
 *
 * 三条设计:
 *   ① **白名单制, 缺省归工程师。** 新加的动作在被人工判定之前一律进折叠区 ——
 *      漏判的方向是"多藏一个", 不是"多露一个危险的";
 *   ② 分类**只影响三维实时页的呈现**, 不动后端、不动 93 个 YAML、不改任何门禁。
 *      每个动作原有的模式门 / 二次确认 / 结果回显全部照旧;
 *   ③ 有漂移看门狗 (tests/three-d/actionAudience.test.js + actions.catalog.json 金样):
 *      目录里出现没分类的动作、白名单里写了不存在的名字、白名单里混进 DEBUG-only 动作,
 *      三种都会红。
 *
 * 判据 (逐条对着 desc 与 kind 过的):
 *   进运维 = 日常操作或流程中断后的人工恢复; 不写点位/路径/标定; 不是 VM 内部原语;
 *            不是 modes:[DEBUG]; 不是资源钩子;
 *            **且同一页上没有更直接的等价控件** (见 SUPERSEDED_BY)。
 */

/**
 * 运维日常动作白名单 (93 条里的 20 条).
 *
 * 每工位一段, 注释写清为什么这几条进、旁边那几条不进 —— 下一个人要调整时能对着理由改,
 * 而不是对着一串名字猜.
 */
export const OPS_ACTIONS = new Set([
  // 地轨: 表面上也只是"把 11Y 挪到某槽位", 但它**带互锁** —— 先断言机械臂在 P1 才允许移轨,
  // 而轴行的定位走 /api/manual/axis/{id}/move 不经过这道门。所以它不算被轴行替代。
  // rail.move 带着整条手臂平移且无槽位语义, 归工程师。
  'rail.ensure',

  // 机械臂: 收敛 / 重连 / 回零三类。
  // robot.query 已降级 (纯读, 见 SUPERSEDED_BY)。
  // jog/step/set_do/enable/disable/clear_error/set_speed_factor 都是 modes:[DEBUG];
  // move_to_point / require_anchor / home_ensure / dwell / tool_action / set_mounted_tool
  // 是 VM 编排原语 (与二维页 ExplorerDock.HIDDEN_ACTIONS 同判)。
  // 回零 = robot.home (动作目录里的「回原点」, 用户定案 2026-08-16): 它是 DEBUG-only,
  // 经 OPS_DEBUG_ONLY_ALLOWED 具名豁免进白名单 —— 非调试模式下按钮由模式门置灰,
  // 后端 403 双保险。曾短暂用 home_ensure 顶替 (2026-08-15), 已按用户要求换回。
  'robot.stop',
  'robot.pause',
  'robot.resume',
  'robot.emergency_stop',
  'robot.connect',
  'robot.home',

  // 展开: 开盖取板 / 关盖 / 把卡在 Tank_State=98 的缸放开 —— 流程中断后操作员要做的就这三件。
  // plate_extend/retract 与气缸行看似重复, 但它们**等到位 DI 才报 DONE**, 比只写输出的
  // 气缸行多一道闭环, 故保留。
  // fill/drain/rinse_*/clean_line 是工艺序, 带溶剂体积参数, 归工程师。
  'develop.init',
  'develop.plate_extend',
  'develop.plate_retract',
  'develop.release_tank',

  // 上样: 只剩复合初始化 (5Z→0 后 4X/6X/7Y→0, 再初始化 4 号泵, 逐轴点四次做不出这个顺序)。
  // place_locate/place_release 已降级 —— 它们与 smp_locator 气缸行双方都不读反馈, 逐字等价。
  // clean 与 flush 驱动 4 号泵且带多个体积参数, 归工程师。
  'sampling.init',

  // 拍照刮板: init 是三轴 + 遮光互锁的复合序; cam_photohome **要等遮光上位**才动 8Y, 是互锁
  // 不是裸定位; press_cylinder 的关方向要等"下压上位" DI, 比气缸行多一道闭环。
  // cam_x335 / locate_cylinder / retr_stoprot 已降级 (见 SUPERSEDED_BY)。
  // scrape / cnc_path / write_* 会动 CNC 与路径表, 归工程师。
  'photoscrape.init',
  'photoscrape.cam_photohome',
  'photoscrape.press_cylinder',

  // 收集: 取出方向。retract/release_clamp 都等原点 DI 才 DONE; transport_extend 是
  // 下压→升降→伸缩的**强制时序**, 拆成三次手点必出事故。
  // clamp/extend/lift_press/collect/bottle_locator 是正向工艺序, 归工程师。
  'collect.init',
  'collect.retract',
  'collect.transport_extend',
  'collect.release_clamp',

  // 上下料: 只剩 init —— 它清 1Z/2Z 的残留 jog 命令位 (搜索类动作被 L2_Reset 中止后会停在
  // TRUE), 轴行的"清错"是 MC_Reset, 不是同一件事。
  // preflight/read_pos/probe_stack 三条纯读已降级 (见 SUPERSEDED_BY)。
  // feed_*/unload_* 做光电边沿搜索会动轴, calib_record 写标定, 都归工程师。
  'feedlift.init',

  // 中转托盘: 两条 locator 已降级 —— 它们"直接赋值、不读原点/动点反馈", 与气缸行逐字等价。
  // 于是本工位常用区为空, 这是有意的: 该做的事就在上面的「气缸开合」区。
])

/**
 * 允许进常用区的 DEBUG-only 动作 (规则③的具名豁免, 逐条给理由).
 *
 * 规则③本意是"运行模式下永远置灰的按钮别放常用区"; robot.home 是用户点名要的
 * 例外 (2026-08-16): 操作员的日常恢复就是在调试模式下回原点, 置灰状态本身也在
 * 传达"先切调试模式"。看门狗据此收窄而不是放开: 豁免集之外混进 DEBUG-only 仍红。
 */
export const OPS_DEBUG_ONLY_ALLOWED = new Set(['robot.home'])

/**
 * 降级溯源: 被移出常用区的动作 → 顶替它的那个直控件.
 *
 * 存在的理由有两个, 缺一不可:
 *   ① **UI**: 工程师区渲染这些动作时在名字下方写一行"已由 xxx 替代" —— 操作员在常用区
 *      找不到熟悉的按钮时, 答案就在原地, 而不是让人以为功能没了;
 *   ② **看门狗**: 单测断言每个 id 真的存在于 manifest 的 axes[] / realtime.mechanisms[]。
 *      顶替件被改名却没人动这里时立刻红 —— 否则降级理由会静默失效, 变成"动作没了、
 *      替代品也没了"。
 *
 * kind:
 *   'axis'       顶替件是「运动轴」区的某一行, id 为 manifest.axes[].id
 *   'mechanism'  顶替件是「气缸开合」区的某一行, id 为 manifest.realtime.mechanisms[].id
 *   'view'       没有可点的顶替件, 信息在别处已呈现 (id 为 null, 看门狗跳过存在性检查)
 */
export const SUPERSEDED_BY = new Map([
  // ── 轴等价 ────────────────────────────────────────────────────────────
  // YAML 全文就是"把刮板 9X 绝对目标固定写为 335 毫米", 且 desc 明写"PLC 动作内不检查
  // 这些前置" —— 零互锁, 与轴行输 335 点「定位」完全等价。
  ['photoscrape.cam_x335',
    { kind: 'axis', id: 'axis_9x', hint: '在「运动轴」区给 axis_9x 输 335 点「定位」完全等价' }],

  // ── 气缸完全等价 (动作与气缸行**双方都不读到位反馈**, 语义逐字相同) ──────
  ['sampling.place_locate',
    { kind: 'mechanism', id: 'smp_locator', hint: '「气缸开合」区的 上样定位气缸 → 开' }],
  ['sampling.place_release',
    { kind: 'mechanism', id: 'smp_locator', hint: '「气缸开合」区的 上样定位气缸 → 关' }],
  ['photoscrape.locate_cylinder',
    { kind: 'mechanism', id: 'ps_locator', hint: '「气缸开合」区的 刮板拍照定位气缸' }],
  ['photoscrape.retr_stoprot',
    { kind: 'mechanism', id: 'ps_rotate', hint: '「气缸开合」区的 刮板拍照旋转气缸 → 关' }],
  ['staging_a.locator_a',
    { kind: 'mechanism', id: 'sta_powder_locator', hint: '「气缸开合」区的 粉末收集器定位气缸' }],
  ['staging_a.locator_b',
    { kind: 'mechanism', id: 'col_bottle_locator', hint: '「气缸开合」区的 溶液收集瓶定位气缸' }],

  // ── 纯读 (对操作员没有可操作含义, 数字/状态在别处已经显示) ────────────────
  ['robot.query',
    { kind: 'view', id: null, hint: '臂姿已按 20Hz 逐帧渲染, 状态释义见本工位「状态」页' }],
  ['feedlift.read_pos',
    { kind: 'axis', id: 'axis_1z', hint: '同页「运动轴」区已实时显示 1Z/2Z 的毫米位置' }],
  ['feedlift.preflight',
    { kind: 'view', id: null, hint: '它是 feed_* 系列发动作前的排障工具, 已随那些动作一起进本区' }],
  ['feedlift.probe_stack',
    { kind: 'view', id: null, hint: '板仓张数见「物料」页; 且它必须紧接 feed_clear→feed_raise 才成立' }],
])

/**
 * 资源门钩子动作 —— 根本不是用户动作, 面板上一概不列.
 *
 * api/app.py::run_action 对 res_gate.hook_actions() 里的名字一律 409;
 * config/resources.yaml 把 device:vacuum_pump 的 activate/deactivate 声明成这两条,
 * 它们由资源门按引用计数驱动, 单独执行会掐掉在跑流程正用着的真空。
 * 泵的人工开关走的是另一条通道: 「模块状态」区的 大真空泵 行
 * (/api/manual/cylinder/pump_vacuum, 只写手动线圈, 不碰资源票)。
 */
export const RESOURCE_GATE_ACTIONS = new Set(['pump.vacuum_on', 'pump.vacuum_off'])

/**
 * 不许插入二次确认的动作.
 *
 * confirmService.js 头注定案: **急停路径上不许出现任何对话框**。
 * 而 ActionQuickForm 是无条件插一步内联确认的, 所以急停必须在这里点名豁免。
 */
export const NO_CONFIRM = new Set(['robot.emergency_stop'])

/** 工程师折叠区的提示语 */
export const ENGINEER_WARNING
  = '以下动作会直接驱动机构、写 PLC 点位或改变机器人状态，属工程调试手段。'
  + '请在工程师指导下使用；不确定后果时，先用上面的常用操作。'

/**
 * 功能: 查一个动作的受众.
 * @param {string} name 动作名
 * @returns {'ops'|'engineer'} 受众
 */
export function audienceOf(name) {
  return OPS_ACTIONS.has(name) ? 'ops' : 'engineer'
}

/**
 * 功能: 取一个动作的降级说明(没被降级过就是空串).
 * @param {string} name 动作名
 * @returns {string} 一句话说明谁顶替了它
 */
export function supersededHint(name) {
  return SUPERSEDED_BY.get(name)?.hint || ''
}

/**
 * 功能: 把某工位的动作清单切成两堆(资源门钩子直接丢弃, 不渲染).
 * @param {object[]} actions 动作定义数组 (/api/actions 目录里属于该工位的那些)
 * @returns {{ops: object[], engineer: object[]}} 两堆
 */
export function splitStationActions(actions) {
  const ops = []
  const engineer = []
  for (const action of actions || []) {
    if (RESOURCE_GATE_ACTIONS.has(action.name)) continue
    ;(audienceOf(action.name) === 'ops' ? ops : engineer).push(action)
  }
  return { ops, engineer }
}
