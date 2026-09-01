/**
 * 功能: 夹爪语义的单一真源 —— "这是不是取料脚本" 与 "夹爪该开到多少".
 *
 * 为什么单独成模块: 这两个判据此前散在四处各写一遍, 且**已经漂了**:
 *   TwinFeed 用 /_pick/(不锚定) 判取料, TrayBinding 用 /_pick$/(锚定) 判同一件事,
 *   于是 robot_scrape_holder_pick_enter 在一边算取料、另一边不算 —— 同一个物理动作,
 *   两层给出相反的答案。开度那边更糟: 实时页有完整三态, 演示近似档只有 0/1 两态,
 *   夹住托盘时演成空爪紧闭 (把物料捏穿)。
 *
 * 三态语义的真源是 three_d/pipeline/rig_map.yaml 头部 (经 device-manifest 的
 * linkages[] 透出), 与后端编译器 clip_compiler.ClipBuilder._gripper_target **逐字同义**:
 *
 *     0          = 张开 (GLB 基准位)
 *     holdValue  = 夹住载荷 (部分闭合)
 *     inputRange[1] = 空爪紧闭 (卸爪前收爪, 免得刮到刀库)
 */

/**
 * 功能: 判断某脚本名是不是"取料脚本"(合爪那一下是去夹住东西, 不是空爪收拢).
 *
 * 不锚定尾部是刻意的: 站侧取料被拆成 *_pick_enter / *_pick_exit 两段, 夹爪动作在
 * enter 那一半 (robot_scrape_holder_pick_enter / robot_collect_holder_pick_enter)。
 * 但也不能只写 /_pick/ —— robot_scrape_holder_pick_exit 名字里同样带 _pick 却没有任何
 * 夹爪动作, 而 robot_*_put_exit 才是松爪那一段。故用 `_pick` 后跟可选的 `_enter` 收尾。
 *
 * @param {string} script 脚本名 (事件里的 event.script, 或近似档展开路径的叶名)
 * @returns {boolean} 是取料脚本
 */
export function isPickScript(script) {
  return /_pick(_enter)?$/.test(String(script || ''))
}

/**
 * 功能: 从展开路径取叶脚本名.
 *
 * 近似档的 where.script 是 `父/子/叶` 这样的路径, 而实时链的 event.script 是单个脚本名。
 * 判据要对两边一致, 就得先把路径收敛成叶名。
 * @param {string} path 脚本路径或脚本名
 * @returns {string} 叶脚本名
 */
export function leafScript(path) {
  return String(path || '').split('/').pop()
}

/**
 * 功能: 算夹爪目标开度 (三态).
 *
 * @param {'gripper-open'|'gripper-close'|string} verb 工具动作
 * @param {object} spec manifest 的 linkages[] 条目 (要 holdValue 与 inputRange)
 * @param {boolean} holding 合爪时爪里有没有载荷; 张开时忽略
 * @returns {number} 归一化开度
 */
// ⚠ 本函数是**载荷无关兜底层**(布尔 holding 拿不到载荷身份): holdValue 只精确于整板;
// 精编译片段的取件闭合已逐件化(clip_compiler._close_value_for: 瓶颈 0.2543 / 粉桶
// 摇篮同心 0.817, 真源 fit_item_grips 经 manifest payload.closeValue)。近似档/实时链
// 停留在兜底层是有意为之, 不是漏改。
export function gripperTarget(verb, spec, holding) {
  if (verb !== 'gripper-close') return 0
  const closed = Number(spec?.inputRange?.[1])
  const full = Number.isFinite(closed) ? closed : 1
  if (!holding) return full
  const hold = Number(spec?.holdValue)
  if (Number.isFinite(hold) && hold > 0) return hold
  warnOnce(spec?.id, full)
  return full
}

/**
 * 功能: 算夹爪的 home 初值 —— 取**对侧端点**, 与目标数值无关.
 *
 * 从前写的是 `target > 0.5 ? 0 : 1`, 在 target = 0.101 (小夹爪 holdValue) 时算出 home=1
 * (空爪紧闭), 正好反了: 通道会从"紧闭"缓动到"夹持", 画面上爪子先合死再张开一点。
 * 合爪的起点必然是张开, 张开的起点必然是闭合, 与开到多少无关。
 * @param {string} verb 工具动作
 * @param {object} spec manifest 的 linkages[] 条目
 * @returns {number} home 初值
 */
export function gripperHome(verb, spec) {
  if (verb === 'gripper-close') return 0
  const closed = Number(spec?.inputRange?.[1])
  return Number.isFinite(closed) ? closed : 1
}

/** @type {Set<string>} 已经就"缺 holdValue"警告过的联动组 (每个只喊一次, 不刷屏) */
const _warned = new Set()

function warnOnce(id, fallback) {
  const key = String(id || '?')
  if (_warned.has(key)) return
  _warned.add(key)
  console.warn(
    `[grip] ${key} 缺 holdValue, 夹持已退回空爪紧闭 ${fallback} —— `
    + '画面上会把载荷捏穿。真源是 rig_map 的 linkages[].holdValue, 补完重跑 gen_twin_manifest。',
  )
}
