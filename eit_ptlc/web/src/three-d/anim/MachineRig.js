/**
 * Studio 适配器。
 *
 * 所有机器状态与刚体约束均由 MachineStateDriver 实现；本类只把 SceneManager 的节点
 * 查询和描边效果接进统一驱动层，并保留旧播放器使用的方法名。
 */
import { MachineStateDriver } from './MachineStateDriver.js'

export class MachineRig extends MachineStateDriver {
  /**
   * @param {object} options
   * @param {import('../twin/scene/SceneManager.js').SceneManager} options.manager
   * @param {object} options.manifest
   */
  constructor({ manager, manifest }) {
    const resolve = (path) => {
      if (!path) return undefined
      const direct = manager.getNode(path)
      if (direct) return direct
      const leaf = path.split('/').pop()
      return leaf ? manager.getNode(leaf) : undefined
    }
    const onHighlight = (names) => {
      const meshes = []
      for (const name of names || []) {
        const node = resolve(name)
        node?.traverse((child) => {
          if (child.isMesh) meshes.push(child)
        })
      }
      manager.effects?.setSelected(meshes)
    }
    super({ manifest, resolve, onHighlight })
    this.manager = manager
    /**
     * 薄层板舞台(可选)。片段里的 `plate` 原语落到这里; 不挂就等于片段只演机器动作。
     * @type {import('../twin/scene/plates/PlateStage.js').PlateStage|null}
     */
    this.plateStage = null
  }

  /** 挂/摘板舞台。宿主(动作页)负责它的生命周期, rig 只借用。 */
  setPlateStage(stage) {
    this.plateStage = stage || null
  }

  /** 执行一条 `plate` 原语(ClipPlayer 的离散事件入口)。 */
  setPlate(payload) {
    return Boolean(this.plateStage?.apply(payload))
  }

  /**
   * 写刮取前沿(ClipPlayer 的 `scrape` 连续通道入口)。
   *
   * 板舞台是可选装置, 没挂就静默跳过(与 setPlate 同一条约定); 清场路径不需要
   * 额外处理 —— home() 已连 plateStage.clear() 一起走, 刮取状态随板一起收掉。
   */
  setScrape(id, phases, region) {
    return Boolean(this.plateStage?.setScrape?.(id, phases, region))
  }

  /** 写点样色带渐现进度(`spot` 连续通道入口), 约定同 setScrape。 */
  setSpot(id, fills, region) {
    return Boolean(this.plateStage?.setSpot?.(id, fills, region))
  }

  /** 写溶剂润湿前沿(`wet` 连续通道入口), 约定同 setScrape。 */
  setWet(id, front, region) {
    return Boolean(this.plateStage?.setWet?.(id, front, region))
  }

  /**
   * 写灯亮度, 并把"受照对象"一并点亮。
   *
   * 视觉纠偏那盏补光灯本体几乎看不见(埋在机台盖板玻璃下 44.5mm), 所以 manifest 用
   * `illuminates` 声明它照的是板 —— 闪光看得见的形态是**板面提亮**, 不是灯泡发光。
   */
  setLight(id, level) {
    const changed = super.setLight(id, level)
    if (this.lights.get(id)?.spec?.illuminates === 'plate') {
      this.plateStage?.setFlash(level)
    }
    return changed
  }

  /**
   * 清场时连板一起收走。
   *
   * 这不是可选的礼貌动作: ClipPlayer 向后 seek 走的是"home() 清场 + 重放 [0,t] 全部
   * 事件", 板留在场上就会在重放时与新出现的那块重叠 —— 拖一次进度条多一块板。
   */
  home() {
    super.home()
    this.plateStage?.clear()
  }

  /** 旧测试/界面名称兼容。 */
  toolParentName(id) {
    return this.attachmentParentName(id)
  }

  /** 旧测试/界面名称兼容。 */
  toolWorldPosition(id) {
    return this.attachmentWorldPosition(id)
  }
}
