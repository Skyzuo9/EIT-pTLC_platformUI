/**
 * 功能: 描边选中的分层仲裁 —— 让多个 UI 写者共用同一条 Effects.selectOutline 通道而不互相抹掉.
 *
 * 背景: `Effects.setSelected(objects)` 是**赋值**语义, 谁最后调谁赢。实时页上同时有三个写者:
 *   ① 工位特写(左栏点工位 / 三维里点中工位)
 *   ② 零件聚焦(点「运动轴」或「气缸开合」里的名字)
 *   ③ 物料选中(右键物料菜单)
 * 过去的做法是"谁清空时顺手把别人的补回来"(MaterialInteraction 的 restoreSelection prop),
 * 那是点状补丁: 每加一个写者, 所有旧写者都得跟着改, 组合数还会漏。
 *
 * 这里改成: 每个写者**只声明自己那一层**, 仲裁器按固定优先级把最高的非空层喂给 Effects。
 * 清掉一层自动露出下一层 —— 新增写者不必动别人, 也不会出现"清一个描边整个消失"。
 *
 * ⚠ 只有实时页与仿真沙盒有多写者。材质台 / 工作台 / 动作台各自**只有一个**写者, 仍直接调
 *   `Effects.setSelected`, 不经过这里 —— 给单写者的页面套一层仲裁是白付出。
 */

/**
 * 层优先级: 越靠前越优先.
 *
 * 物料 > 零件 > 工位 —— 选择越具体越该被看见: 用户刚右键点了某个瓶子, 不该被"整个工位在
 * 选中态"盖回去; 反过来关掉瓶子的卡片, 应该露出他之前点的那根轴, 而不是一片空白。
 */
export const OUTLINE_LAYERS = Object.freeze(['material', 'part', 'station'])

export class OutlineArbiter {
  /**
   * 功能: 建立仲裁器.
   * @param {object} effects Effects 实例(只用到 setSelected; 传 null 时整体降为空转)
   */
  constructor(effects) {
    this.effects = effects || null
    /** @type {Map<string, object[]>} 层 -> 该层当前声明的对象数组 */
    this.layers = new Map()
  }

  /**
   * 功能: 声明某一层的描边对象(空数组即撤销该层).
   * @param {'material'|'part'|'station'} layer 层名
   * @param {object[]} objects 网格数组(Selection 不递归 Group, 必须是 mesh)
   * @returns {void}
   */
  set(layer, objects) {
    // 层名写错要当场炸而不是静默不生效 —— 静默的话表现是"描边偶尔不出现", 极难查
    if (!OUTLINE_LAYERS.includes(layer)) throw new Error(`未知的描边层: ${layer}`)
    const list = Array.isArray(objects) ? objects : []
    if (list.length) this.layers.set(layer, list)
    else this.layers.delete(layer)
    this._apply()
  }

  /**
   * 功能: 换一条 Effects 链并把已声明的层重放上去.
   *
   * 必须有这个: 切画质档会整条重建后期链(低档位甚至没有链, effects 为 null), 新链上是空的
   * 选择集。仲裁器持有的层才是权威状态, 不重放的话切一次档用户的选中描边就凭空没了。
   * @param {object|null} effects 新的 Effects 实例(null 表示当前档位没有后期链)
   * @returns {void}
   */
  attach(effects) {
    this.effects = effects || null
    this._apply()
  }

  /**
   * 功能: 撤销某一层(等价于 set(layer, [])).
   * @param {'material'|'part'|'station'} layer 层名
   * @returns {void}
   */
  clear(layer) {
    this.set(layer, [])
  }

  /** 功能: 撤销全部层(页面卸载/断线时用). */
  clearAll() {
    this.layers.clear()
    this._apply()
  }

  /**
   * 功能: 取当前生效的那一层(供单测与调试; 没有任何层时为 null).
   * @returns {string|null} 层名
   */
  winner() {
    return OUTLINE_LAYERS.find((layer) => this.layers.has(layer)) || null
  }

  /** 功能: 把最高的非空层推给 Effects. */
  _apply() {
    const layer = this.winner()
    this.effects?.setSelected?.(layer ? this.layers.get(layer) : [])
  }
}
