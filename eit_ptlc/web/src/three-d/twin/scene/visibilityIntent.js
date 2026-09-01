/**
 * 功能: `node.visible` 的多写者仲裁 —— 谁想藏就登记一条"意图", 由本模块合成最终显隐.
 *
 * 为什么需要它: 同一个 `LIQUID_*` 节点今天有三个写方 ——
 *   1. `ViewTools.hide` / `isolate`(用户手动隐藏/隔离);
 *   2. `ViewTools.setHelpersVisible`(示意体总开关);
 *   3. 驱动层"这缸此刻没液, 别画了"(MachineStateDriver.setLiquidMl / TwinBindings).
 * 三方各写各的, 结果是"谁最后写谁赢": 在动作页隔离几个零件之后播一段注液
 * (MotionWorkbench.vue 的 isolate 按钮 -> ViewTools.isolate 按 `child.isMesh` 收集,
 * 而 `LIQUID_*` 恰是裸网格, 必被隔离藏起), 液面盒会在下一次 setLiquidMl 时自己弹回画面.
 *
 * 规则只有一条: **只要还有任一方登记着 hidden, 节点就不显示**.
 *
 * 登记表挂在 `node.userData` 而不是某个类的实例上 —— 三个写方分属三个模块、生命周期
 * 各不相同(ViewTools 随页面走, rig 每次改参都重建), 挂实例上必然对不齐.
 *
 * ⚠ 本模块只管**参与仲裁的节点**. 从没登记过意图的节点一律不碰, 所以对"减配视图"
 * (WorkbenchScene 直接写 visible)这类圈外写方, 行为与本模块上线前逐位相同 ——
 * 这正是 releaseHidden 要收一个 fallbackVisible 的缘故.
 */

/** 隐藏意图的登记方. 加新成员时想清楚它的生命周期由谁负责撤销. */
export const HIDE_OWNER = Object.freeze({
  /** ViewTools.hide / isolate —— 用户手动隐藏, 由 show/showAll 撤销 */
  VIEW: 'view',
  /** ViewTools.setHelpersVisible —— 示意体总开关 */
  HELPERS: 'helpers',
  /** 驱动层: 这处液面此刻是空的, 由 setLiquidMl / dispose 撤销 */
  EMPTY: 'empty',
})

/** userData 上的登记表键名; 带前缀避免与 glTF 自带的 extras 撞名 */
const KEY = '__ptlcHiddenBy'

/**
 * 功能: 这个节点此刻是否还有人登记着隐藏.
 * @param {object} node three.js 对象(或任何带 userData 的桩)
 * @returns {boolean} 有任一登记为真
 */
export function isHiddenByAny(node) {
  const table = node?.userData?.[KEY]
  return Boolean(table && Object.keys(table).length)
}

/**
 * 功能: 这个节点是否参与仲裁(有过任何一方登记).
 *
 * 用途: 圈外写方(减配视图)藏起来的东西不该被仲裁点亮, 调用方据此决定用不用自己的权威值.
 *
 * @param {object} node three.js 对象
 * @returns {boolean} 有过登记表即为真(即使当前表已空)
 */
export function hasHideIntent(node) {
  return Boolean(node?.userData?.[KEY])
}

/**
 * 功能: 登记一条隐藏意图并按"有任一意图即隐藏"重算 visible.
 *
 * @param {object} node three.js 对象
 * @param {string} owner HIDE_OWNER 之一
 * @returns {void}
 */
export function holdHidden(node, owner) {
  if (!node) return
  const table = node.userData[KEY] || (node.userData[KEY] = {})
  table[owner] = true
  node.visible = false
}

/**
 * 功能: 撤销一条隐藏意图.
 *
 * 撤销后若**还有别人**登记着, 节点保持隐藏(这正是本模块存在的意义);
 * 若已无人登记, 才采用调用方给的权威值 —— ViewTools 传的是它隐藏台账里记的原值,
 * 驱动层传 true.
 *
 * @param {object} node three.js 对象
 * @param {string} owner HIDE_OWNER 之一
 * @param {boolean} [fallbackVisible] 无人登记时该显示成什么; 缺省 true
 * @returns {void}
 */
export function releaseHidden(node, owner, fallbackVisible = true) {
  if (!node) return
  const table = node.userData[KEY]
  if (!table) {
    node.visible = fallbackVisible
    return
  }
  delete table[owner]
  node.visible = Object.keys(table).length ? false : fallbackVisible
}

/**
 * 功能: holdHidden / releaseHidden 的开关式写法 —— 供"按条件显隐"的调用点少写一个 if.
 *
 * @param {object} node three.js 对象
 * @param {string} owner HIDE_OWNER 之一
 * @param {boolean} hidden 是否要藏
 * @param {boolean} [fallbackVisible] 撤销且无人登记时的权威值
 * @returns {void}
 */
export function setHidden(node, owner, hidden, fallbackVisible = true) {
  if (hidden) holdHidden(node, owner)
  else releaseHidden(node, owner, fallbackVisible)
}
