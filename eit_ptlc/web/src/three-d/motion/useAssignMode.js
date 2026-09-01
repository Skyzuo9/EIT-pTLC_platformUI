/**
 * 功能: 指认滑车成员模式 —— 页内临时换装 raw 模型点选零件, 写回 rig_map 后全链重跑.
 *
 * 为什么要换模: official 模型的静态件已按材质合并(STATIC 块), 零件级拾取只有 raw.glb
 * 还保留。指认时临时换装 raw, 写回 carriage_members 后全链重跑并原地切回, 新轴立即
 * 可驱动。已 rigged 的轴同样可以进来"修改成员"(预选既有 carriage_members)。
 *
 * phase: entering(切换 raw 模型) | active(拾取中) | saving(写回) |
 *        rebuilding(全链重跑) | leaving(切回 official)
 */
import { computed, ref, shallowRef } from 'vue'

import { applyRobotHomePose } from '../anim/robotHomePose.js'
import * as api from '../workbench/authoringApi.js'
import { OFFICIAL_CR5_NAMES } from '../workbench/officialCr5Names.js'
import { PartIndex } from '../workbench/PartIndex.js'
import { SelectionModel } from '../workbench/selectionModel.js'
import { WorkbenchScene } from '../workbench/WorkbenchScene.js'
import { patchRigMap, readRigMap, resetRigBaseline } from './rigWriter.js'
import { patchRigMapCarriage, readRigMapAxis } from './rigPatch.js'

/** 指认模式加载的原始模型: 唯一保留零件级粒度的产物 */
const RAW_MODEL_URL = '/api/3d/assets/models/raw.glb'

/**
 * 功能: 提供指认模式的全部状态与动作.
 *
 * @param {object} options 参数对象
 * @param {import('vue').ShallowRef} options.manager SceneManager 的 shallowRef
 * @param {import('vue').ShallowRef} options.tools ViewTools 的 shallowRef(与离线栈共用)
 * @param {object} options.state 场景的 { disposed } 标志
 * @param {string} options.modelUrl 退出时切回的 official 模型地址
 * @param {(url: string, opts?: object) => Promise<object|null>} options.swapModel 换模
 * @param {() => void} options.detachStack 拆离线栈
 * @param {(manifest: object) => void} options.attachStack 挂离线栈
 * @param {() => Array} options.semanticsOf 取当前语义条目(找标签用)
 * @param {(text: string) => void} options.notify 提示回调
 * @returns {object} 指认模式接口
 */
export function useAssignMode({
  manager,
  tools,
  state,
  modelUrl,
  swapModel,
  detachStack,
  attachStack,
  semanticsOf,
  notify,
}) {
  /** null = 正常动作模式 */
  const assign = ref(/** @type {object|null} */ (null))
  /** 选中集重算扳机 */
  const tick = ref(0)
  /** 重跑进度(waitRebuild 状态) */
  const rebuild = ref(/** @type {object|null} */ (null))

  /** 非响应式引用: three 对象图 */
  let scene = null
  let index = null
  let model = null
  let savedQuality = ''

  const count = computed(() => {
    tick.value
    return model?.selected.size || 0
  })
  const runningStep = computed(
    () => (rebuild.value?.steps || []).find((step) => step.status === 'running')?.label || '',
  )

  /**
   * 功能: 拆掉指认栈(幂等).
   * @returns {void}
   */
  function teardown() {
    scene?.dispose()
    scene = null
    tools.value?.dispose()
    tools.value = null
    index = null
    model = null
    rebuild.value = null
  }

  /**
   * 功能: 三维拾取回调(空点清、Ctrl 加选、单点单选).
   * @param {string|null} key 零件键
   * @param {boolean} additive 是否加选
   * @returns {void}
   */
  function pick(key, additive) {
    if (!model) return
    if (!key) {
      if (!additive) model.clearSelection()
    } else if (additive) {
      model.toggle(key)
    } else {
      model.select([key])
    }
    tick.value += 1
  }

  /**
   * 功能: 取选中集的网格(工具栏隐藏/隔离用).
   * @returns {Array} 网格数组
   */
  function meshes() {
    if (!index || !model) return []
    const found = new Set()
    for (const key of model.selected) {
      index.get(key)?.object?.traverse((child) => {
        if (child.isMesh) found.add(child)
      })
    }
    return [...found]
  }

  /**
   * 功能: 进入指认模式 —— 换装 raw 模型, 预选该轴既有成员.
   * @param {string} axisId 轴 id
   * @returns {Promise<void>}
   */
  async function start(axisId) {
    if (assign.value) return
    const label = semanticsOf().find((entry) => entry.params?.axisId === axisId)?.label || axisId
    assign.value = { axisId, label, phase: 'entering', error: '' }

    try {
      // 先读后拆: rig_map 读失败可原地退回, 不动现有场景
      const rigText = await readRigMap()
      if (state.disposed) return
      const axisEntry = readRigMapAxis(rigText, axisId)
      if (!axisEntry) throw new Error(`rig_map 里没有轴 ${axisId}`)

      detachStack()
      savedQuality = manager.value.quality
      // raw 2000+ 绘制调用: 降到仅描边的 lite 档(与装配台同款)
      manager.value.setQuality('lite')

      // 指认是创作路径, raw.glb 无 manifest 构建戳可用 —— 每次强刷保证重跑后立即见新
      await swapModel(RAW_MODEL_URL, { bust: true })
      if (state.disposed) return

      let chinese = new Map()
      try {
        chinese = PartIndex.parseNamesCsv(await api.readFile('names_csv'))
      } catch {
        // 没有 names.csv 不致命, 树里少中文列
      }
      if (state.disposed) return
      for (const [en, zh] of OFFICIAL_CR5_NAMES) {
        if (!chinese.has(en)) chinese.set(en, zh)
      }

      index = new PartIndex(manager.value.machineRoot, chinese)
      // 时序约束: PartIndex 之后再摆 home 姿态(sizeMm 是世界包围盒口径, 须按零位测)
      await applyRobotHomePose(manager.value)
      if (state.disposed) return

      // 修改模式: 既有 carriage_members 的 equals 名展开为索引键, 预选中
      model = new SelectionModel()
      const preselect = []
      for (const member of axisEntry.carriage_members || []) {
        if (member?.equals) preselect.push(...(index.keysForSavedName?.(member.equals) || []))
      }
      if (preselect.length) model.select(preselect)

      scene = new WorkbenchScene({
        manager: manager.value,
        index,
        model,
        onPick: pick,
        getEffectiveDeletes: () => null,
        whiteMode: false, // 指认要认零件长相, 用管线材质(raw 已赋材质, 2026-08 起)
      })
      tick.value += 1
      assign.value = { ...assign.value, phase: 'active' }
      notify(preselect.length
        ? `已载入原始模型并预选 ${preselect.length} 个既有成员(Ctrl 点击增删)`
        : '已载入原始模型, 点选随该轴移动的零件(Ctrl 加选, 选装配根=整组随动)')
    } catch (err) {
      if (state.disposed) return
      notify(`进入指认失败: ${err.message}`)
      await exit('', { skipReload: assign.value?.phase === 'entering' && !scene })
    }
  }

  /**
   * 功能: 写回 carriage_members 并全链重跑.
   * @returns {Promise<void>}
   */
  async function save() {
    if (!model?.selected.size || !index || assign.value?.phase !== 'active') {
      notify('请先选中随该轴移动的零件(Ctrl 加选)')
      return
    }
    const axisId = assign.value.axisId
    // 同名多实例分组计数: 选 2 个同名压板 -> {equals: 名, expect_count: 2}
    const byName = new Map()
    for (const key of model.selected) {
      const name = index.savedNameOf?.(key) ?? key
      byName.set(name, (byName.get(name) || 0) + 1)
    }
    // 歧义守卫: 管线按名字匹配, 无法区分同名实例 —— 选了名字的一部分实例(如两套
    // 上料机构各有一块同名连接板, 只选其一)时, 写回必然在重跑时 expect_count 失配
    // 硬失败(实测 axis_1z 因此卡死全链). 提前拦下并给出可行动的指引.
    const ambiguous = []
    for (const [name, num] of byName) {
      const total = index.keysForSavedName?.(name)?.length ?? num
      if (total !== num) ambiguous.push(`「${name}」选了 ${num}/${total} 个`)
    }
    if (ambiguous.length) {
      notify(
        `同名实例无法按名字区分: ${ambiguous.join('、')}。`
        + '要么把同名实例全部选上(它们一起随轴动), 要么在 CAD/管线侧改名区分后再指认。',
      )
      return
    }
    assign.value = { ...assign.value, phase: 'saving' }
    try {
      const members = [...byName.entries()]
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([name, num]) => ({ equals: name, expect_count: num }))

      // 写前重读由 patchRigMap 负责(防并发写: 标定子页也在写 rig_map)
      const written = await patchRigMap((text) => {
        if (!readRigMapAxis(text, axisId)) throw new Error(`rig_map 里没有轴 ${axisId}`)
        return patchRigMapCarriage(text, axisId, members)
      })
      if (state.disposed) return
      if (written.conflict === true) {
        assign.value = { ...assign.value, phase: 'active' }
        notify('rig_map 在此期间被其它会话改过, 已重新读取 —— 请再点一次写回')
        return
      }

      assign.value = { ...assign.value, phase: 'rebuilding' }
      await api.startRebuild([])
      const final = await api.waitRebuild((status) => {
        if (state.disposed) throw new Error('view disposed')
        rebuild.value = status
      })
      if (state.disposed) return
      resetRigBaseline()
      await exit(final.error || '')
    } catch (err) {
      if (state.disposed) return
      if (assign.value) assign.value = { ...assign.value, phase: 'active' }
      notify(`写回失败: ${err.message}`)
    }
  }

  /**
   * 功能: 取消指认(不写回).
   * @returns {Promise<void>}
   */
  async function cancel() {
    if (assign.value?.phase !== 'active') return
    await exit('')
  }

  /**
   * 功能: 退出指认 —— 拆指认栈、切回 official 模型、重建离线栈.
   * @param {string} errMsg 重跑错误(空=成功/取消)
   * @param {object} [options] skipReload: 进入早期失败时场景未动, 不必换模
   * @returns {Promise<void>}
   */
  async function exit(errMsg, { skipReload = false } = {}) {
    if (assign.value) assign.value = { ...assign.value, phase: 'leaving' }
    teardown()
    if (!skipReload) {
      if (savedQuality) manager.value.setQuality(savedQuality)
      // 重跑成功后 deploy 已换新 manifest —— 先拿它, 再用构建戳强制拉新模型
      const manifest = await swapModel(modelUrl, { freshManifest: true })
      if (state.disposed || !manifest) return
      attachStack(manifest)
    }
    if (state.disposed) return

    assign.value = null
    notify(errMsg
      ? `重跑失败: ${errMsg}(rig_map 已写回, 修复后可重跑)`
      : '已回到动作模式')
  }

  return { assign, tick, rebuild, count, runningStep, start, save, cancel, exit, pick, meshes, teardown }
}
