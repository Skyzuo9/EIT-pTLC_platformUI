// PLC 程序 (CODESYS POU) 编辑 store
// =================================
// 管理 POU 列表 / 当前 POU 的声明(VAR)+实现(ST) 文本 / 脏标记 / 编译结果 / IDE worker 状态。
// 保存语义 (沿用后端 README 约定): 编译会先把当前文本写入内存工程 (save=false) 再 build 看错误;
// 满意后点「保存到工程」(save=true) 才落盘 .project。全下载会先走 PLC 安全停机握手，
// 下载后由 worker 自动启动，并等待 EtherCAT 恢复及 5Z→4X 自动回零完成。
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api, errText } from '../api'

export const usePlcStore = defineStore('plc', () => {
  const sessionStatus = ref(null)
  const sessionBusy = ref(false)
  const sessionMsg = ref('')

  // ---- POU 列表 (左 Dock「PLC」标签) ----
  const pous = ref([])              // [{path, name, has_impl, has_decl}]
  const loadingPous = ref(false)
  const pousError = ref('')

  // ---- 当前 POU 编辑态 (中区双编辑器) ----
  const currentPath = ref('')
  const decl = ref('')             // 声明 VAR 文本 (CodeEditor v-model)
  const impl = ref('')             // 实现 ST 文本 (CodeEditor v-model)
  const hasDecl = ref(false)
  const hasImpl = ref(false)
  const loadingPou = ref(false)
  const pouError = ref('')
  const dirty = ref(false)         // 编辑后未落盘 (仅「保存到工程」清除)

  // ---- 编译 / 保存 (右栏) ----
  const saving = ref(false)
  const compiling = ref(false)
  const compileResult = ref(null)  // {error_count, warning_count, errors:[{severity,text}], warnings:[...]} 或 {error}
  const saveMsg = ref('')

  // ---- IDE worker 状态 (外部 PLC 软件 InoProShop 连接) ----
  const workerStatus = ref(null)   // {state, project, allow_deploy}
  const statusBusy = ref(false)    // 连接进行中 (connect 在途)
  const statusError = ref('')      // 连接失败信息 (供「点击连接重新拉起」提示)
  const connected = ref(false)     // InoProShop 是否已显式连接 (默认 false, 不自动拉起)

  // ---- 部署 (全下载到真机; 安全握手后下载，随后自动启动并等待 PLC Ready) ----
  const allowDeploy = ref(false)   // 后端 codesys.allow_deploy (status 返回; false 则按钮禁用 + 后端 403)
  const onlineStatus = ref(null)   // {ready, state, reason} (下发前置探测; 软提示, 非硬门控)
  const deploying = ref(false)
  const deployMsg = ref('')
  const deployResult = ref(null)   // {downloaded/deployed, started, ready, retryable, stage, ...}
  const deployStage = ref('')      // 当前内存进度 phase；部署响应返回后回落为最终 stage
  const deployProgress = ref(null) // GET /deploy/status 纯内存阶段快照，不占用 CODESYS worker
  const deployRetryLocked = ref(false) // 已下载但未就绪/结果不明确后，本页面会话禁止再次下载
  const reconcileBusy = ref(false)
  let deployPollGeneration = 0

  // ---- 版本历史 (.project 全量快照) ----
  const versions = ref([])         // [{rev, ts, sha256, size, deployed_at, message}] (升序)
  const versionsBusy = ref(false)
  const versionMsg = ref('')

  // ---- OPC 符号导出 (当前 POU/GVL 变量的 symbol pragma; 改后需编译+下载生效) ----
  const symbols = ref([])          // [{name, type, exported}] 当前 POU 声明里的变量
  const symbolsBusy = ref(false)
  const symbolsMsg = ref('')

  async function loadPous() {
    loadingPous.value = true
    pousError.value = ''
    try {
      const r = await api.listPous()
      pous.value = r.pous || []
    } catch (e) {
      pousError.value = errText(e)
    } finally {
      loadingPous.value = false
    }
  }

  async function loadPou(path) {
    if (!path) {
      return
    }
    // 未连接时不读 POU (getPou 会隐式拉起 InoProShop); 挡住直链 /plc/pou/xxx 导航
    if (!connected.value) {
      currentPath.value = path
      pouError.value = '未连接 —— 请先在左栏点击「连接」'
      return
    }
    loadingPou.value = true
    pouError.value = ''
    compileResult.value = null
    saveMsg.value = ''
    try {
      const r = await api.getPou(path)
      currentPath.value = r.path || path
      decl.value = r.declaration || ''
      impl.value = r.implementation || ''
      hasDecl.value = !!r.has_decl
      hasImpl.value = !!r.has_impl
      dirty.value = false
      symbols.value = []
      symbolsMsg.value = ''
      if (hasDecl.value) {
        await loadSymbols()     // 有声明则拉一次符号导出态 (供符号面板复选框)
      }
    } catch (e) {
      pouError.value = errText(e)
      currentPath.value = path
    } finally {
      loadingPou.value = false
    }
  }

  // CodeEditor 改动入口: 同步文本 + 置脏 (载入时不经此, 故不误置脏)
  function setDecl(v) {
    decl.value = v
    dirty.value = true
  }
  function setImpl(v) {
    impl.value = v
    dirty.value = true
  }

  // 把当前文本写入工程 (toDisk=true 落盘 .project, false 仅内存供随后编译)
  async function _write(toDisk) {
    await api.savePou(currentPath.value, {
      declaration: hasDecl.value ? decl.value : undefined,
      implementation: hasImpl.value ? impl.value : undefined,
      save: toDisk,
    })
  }

  // 保存到工程 (落盘)
  async function save() {
    if (!currentPath.value) {
      return
    }
    saving.value = true
    saveMsg.value = ''
    try {
      await _write(true)
      dirty.value = false
      saveMsg.value = '已保存到工程 ✓'
    } catch (e) {
      saveMsg.value = '保存失败: ' + errText(e)
    } finally {
      saving.value = false
    }
  }

  // 编译: 先把当前文本写入内存工程 (save=false) 再 build, 返回 errors/warnings
  async function compile() {
    if (!currentPath.value) {
      return
    }
    compiling.value = true
    compileResult.value = null
    saveMsg.value = ''
    try {
      await _write(false)
      compileResult.value = await api.compilePou()
    } catch (e) {
      compileResult.value = { error: errText(e) }
    } finally {
      compiling.value = false
    }
  }

  // 显式连接外部 PLC 软件 (InoProShop): 点「连接」才拉起, 成功后填充左栏 POU 列表
  async function loadSession() {
    sessionBusy.value = true
    try {
      sessionStatus.value = await api.plcSession()
      sessionMsg.value = ''
      return sessionStatus.value
    } catch (e) {
      sessionMsg.value = '会话状态读取失败: ' + errText(e)
      return null
    } finally {
      sessionBusy.value = false
    }
  }

  async function takeoverSession() {
    sessionBusy.value = true
    try {
      sessionStatus.value = await api.plcSessionTakeover('operator takeover from PLC UI')
      connected.value = false
      workerStatus.value = null
      statusError.value = ''
      sessionMsg.value = '已接管 PLC 会话；窗口继续保活，自动读写已暂停'
    } catch (e) {
      sessionMsg.value = '接管失败: ' + errText(e)
    } finally {
      sessionBusy.value = false
    }
  }

  async function releaseSession() {
    sessionBusy.value = true
    try {
      sessionStatus.value = await api.plcSessionRelease()
      statusError.value = ''
      sessionMsg.value = '已释放给上位机/自动化客户端'
    } catch (e) {
      sessionMsg.value = '释放失败: ' + errText(e)
    } finally {
      sessionBusy.value = false
    }
  }

  async function connect() {
    statusBusy.value = true
    statusError.value = ''
    try {
      await loadSession()
      if (sessionStatus.value?.manual_control) {
        connected.value = false
        workerStatus.value = null
        statusError.value = '用户已接管 PLC 会话，释放后才能由上位机读取/编译'
        return
      }
      // plcStatus 经后端 ensure_worker 懒启动 InoProShop (首次 ~14s, 弹 GUI 窗口)
      workerStatus.value = await api.plcStatus()
      allowDeploy.value = !!workerStatus.value?.allow_deploy
      connected.value = true
      await loadSession()
      await loadPous()
      await loadVersions()    // 连接后拉一次版本历史 (读 index.json, 轻量)
    } catch (e) {
      statusError.value = errText(e)
      workerStatus.value = null
      connected.value = false
    } finally {
      statusBusy.value = false
    }
  }

  // ---- 部署 ----
  // 下发前置探测 (创建 online 句柄; 软提示真机是否可对接, 真正可达性需 login 即 deploy 本身)
  async function loadOnlineStatus() {
    try {
      onlineStatus.value = await api.plcOnlineStatus()
    } catch (e) {
      onlineStatus.value = { ready: false, state: null, reason: errText(e) }
    }
  }

  function _downloaded(r) {
    return !!(r && (r.downloaded === true || r.deployed === true))
  }

  function _ready(r) {
    // 完整下载只有 PLC 启动状态机明确返回 READY 才算成功。
    // started=true 仅说明运行命令曾发出，不能证明 EtherCAT、使能和 5Z→4X 回零完成。
    return !!r && r.ready === true
  }

  function _outcomeUncertain(r) {
    return !!(r && (r.result_uncertain === true || r.stage === 'deploy_outcome_unknown'))
  }

  function _maintenanceRecoveryRequired(r) {
    return !!(r && (r.maintenance_recovery_required === true ||
      r.stage === 'maintenance_recovery_required'))
  }

  function _formatDeployFailure(r) {
    const reason = r.reason || r.start_error || 'PLC 未返回明确原因'
    const state = r.startup_state == null ? '' : `，启动状态 ${r.startup_state}`
    const code = r.startup_error_code ? `，错误码 ${r.startup_error_code}` : ''
    if (_maintenanceRecoveryRequired(r)) {
      return `程序未下载，但 PLC 下载准备态未确认恢复：${reason}。维护锁保持，请人工恢复并完成只读安全对账。`
    }
    if (_outcomeUncertain(r)) {
      return `下载结果不明确：${reason}${state}${code}。本会话已禁止再次下载，请人工核对 PLC 在线版本与设备状态。`
    }
    return `程序已下载，但 PLC 未就绪：${reason}${state}${code}。本会话已禁止再次下载，请人工核对在线版本，禁止自动重发。`
  }

  async function loadDeployProgress() {
    try {
      const progress = await api.plcDeployStatus()
      deployProgress.value = progress
      if (progress?.phase) deployStage.value = progress.phase
      if (progress?.status === 'error' && progress?.retryable === false &&
          progress?.downloaded !== false) {
        deployRetryLocked.value = true
      }
      return progress
    } catch (_) {
      // 阶段遥测是旁路观测，短暂失败不能影响正在执行的非幂等下载请求。
      return null
    }
  }

  function _startDeployProgressPolling() {
    const generation = ++deployPollGeneration
    ;(async () => {
      while (deploying.value && generation === deployPollGeneration) {
        await loadDeployProgress()
        await new Promise((resolve) => setTimeout(resolve, 350))
      }
    })()
    return generation
  }

  function _stopDeployProgressPolling(generation) {
    if (generation === deployPollGeneration) deployPollGeneration += 1
  }

  // 全下载到真机：后端先编译与安全停机握手，再强制全下载、自动启动并等待 PLC Ready。
  async function deploy() {
    if (deployRetryLocked.value) {
      deployMsg.value = '已禁止再次下载；请先人工核对 PLC 在线版本与设备状态，再执行只读安全对账。'
      return
    }
    deploying.value = true
    deployMsg.value = ''
    deployResult.value = null
    deployProgress.value = null
    deployStage.value = 'running'
    const pollGeneration = _startDeployProgressPolling()
    try {
      const r = await api.plcDeploy()
      deployResult.value = r
      deployStage.value = r.stage || (_ready(r) ? 'ready' : (_downloaded(r) ? 'startup_failed' : 'precheck_failed'))
      if (_downloaded(r) && _ready(r)) {
        deployMsg.value = '已安全下载、自动启动并完成 5Z→4X 回零，PLC 已就绪 ✓'
      } else if (_downloaded(r) || _outcomeUncertain(r) || _maintenanceRecoveryRequired(r)) {
        deployRetryLocked.value = true
        deployMsg.value = _formatDeployFailure(r)
      } else {
        deployMsg.value = '下发中止，程序未下载: ' + (r.reason || '编译或安全准备未通过')
      }
      if (_downloaded(r)) {
        await loadVersions()  // 部署已打标记, 刷新版本台账
      }
    } catch (e) {
      const detail = e?.response?.data?.detail
      const structured = detail && typeof detail === 'object' ? detail : null
      if (structured) {
        deployResult.value = structured
        deployStage.value = structured.stage || 'precheck_failed'
        if (_downloaded(structured) || _outcomeUncertain(structured) || _maintenanceRecoveryRequired(structured)) {
          deployRetryLocked.value = true
          deployMsg.value = _formatDeployFailure(structured)
        } else {
          deployMsg.value = '下发前检查失败，程序未下载: ' + (structured.reason || JSON.stringify(structured))
        }
      } else {
        deployStage.value = 'precheck_failed'
        deployMsg.value = '下发前检查失败，程序未下载: ' + errText(e)
      }
    } finally {
      _stopDeployProgressPolling(pollGeneration)
      await loadDeployProgress()
      await loadSession()
      deploying.value = false
    }
  }

  async function reconcileMaintenance() {
    reconcileBusy.value = true
    try {
      const r = await api.plcDeployReconcile(true)
      if (r.released) {
        deployRetryLocked.value = false
        deployMsg.value = '在线版本已人工核对，PLC READY 只读对账通过，维护锁已解除 ✓'
      } else {
        deployMsg.value = r.reason || '只读安全对账未通过，维护锁保持'
      }
      return r
    } catch (e) {
      deployMsg.value = '只读安全对账失败，维护锁保持: ' + errText(e)
      return null
    } finally {
      await loadSession()
      reconcileBusy.value = false
    }
  }

  // ---- 版本历史 ----
  async function loadVersions() {
    versionsBusy.value = true
    try {
      versions.value = await api.plcVersions()
    } catch (e) {
      versionMsg.value = '加载版本失败: ' + errText(e)
    } finally {
      versionsBusy.value = false
    }
  }

  // 手动给当前工程打一版快照 (内容未变则不新增)
  async function snapshot(message) {
    versionsBusy.value = true
    versionMsg.value = ''
    try {
      const r = await api.plcSnapshot(message)
      versionMsg.value = r.snapshotted ? ('已快照 ' + (r.version?.rev || '') + ' ✓') : '内容未变, 未新增快照'
      await loadVersions()
    } catch (e) {
      versionMsg.value = '快照失败: ' + errText(e)
    } finally {
      versionsBusy.value = false
    }
  }

  // ---- OPC 符号导出 (pragma 管理) ----
  // 读当前 POU 声明里各变量是否已加 symbol 导出 pragma (后端解析, 单一真源)
  async function loadSymbols() {
    if (!currentPath.value || !connected.value) {
      symbols.value = []
      return
    }
    symbolsBusy.value = true
    try {
      const r = await api.plcListSymbols(currentPath.value)
      symbols.value = r.symbols || []
    } catch (e) {
      symbols.value = []
      symbolsMsg.value = '读取符号失败: ' + errText(e)
    } finally {
      symbolsBusy.value = false
    }
  }

  // 切换某变量的 OPC 导出 (后端增删 pragma + 落盘); 需先保存编辑器改动, 改后需编译+下载才生效
  async function toggleSymbol(name, enabled) {
    if (dirty.value) {
      symbolsMsg.value = '请先「保存到工程」编辑器改动, 再切换符号导出'
      return
    }
    symbolsBusy.value = true
    symbolsMsg.value = ''
    try {
      await api.plcSetSymbol(currentPath.value, name, enabled)
      await loadPou(currentPath.value)   // 重读声明+符号: 编辑器显示新增 pragma, 复选框同步
      symbolsMsg.value = '已标记 —— 需「编译」+「下载到设备」才在 OPC 生效'
    } catch (e) {
      symbolsMsg.value = '切换失败: ' + errText(e)
    } finally {
      symbolsBusy.value = false
    }
  }

  // 还原某版到活动工程 (后端先停 worker 释放文件锁再覆盖; 还原后需重新连接打开还原后工程)
  async function restore(rev) {
    versionsBusy.value = true
    versionMsg.value = ''
    try {
      await api.plcRestore(rev)
      versionMsg.value = '已还原 ' + rev + ' —— worker 已停, 请重新「连接」打开还原后工程'
      connected.value = false   // worker 已被停, 回到未连接态
      workerStatus.value = null
      await loadVersions()
    } catch (e) {
      versionMsg.value = '还原失败: ' + errText(e)
    } finally {
      versionsBusy.value = false
    }
  }

  return {
    pous, loadingPous, pousError,
    currentPath, decl, impl, hasDecl, hasImpl, loadingPou, pouError, dirty,
    saving, compiling, compileResult, saveMsg,
    workerStatus, statusBusy, statusError, connected,
    sessionStatus, sessionBusy, sessionMsg,
    allowDeploy, onlineStatus, deploying, deployMsg, deployResult, deployStage, deployProgress, deployRetryLocked, reconcileBusy,
    versions, versionsBusy, versionMsg,
    symbols, symbolsBusy, symbolsMsg,
    loadPous, loadPou, setDecl, setImpl, save, compile, connect,
    loadSession, takeoverSession, releaseSession,
    loadOnlineStatus, loadDeployProgress, deploy, reconcileMaintenance, loadVersions, snapshot, restore,
    loadSymbols, toggleSymbol,
  }
})
