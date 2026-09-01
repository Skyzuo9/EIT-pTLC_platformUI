// 后端 REST 客户端 (经 vite 代理 /api -> FastAPI)
import axios from 'axios'

const http = axios.create({ baseURL: '/' })

// 供需要动态路径的三维手动会话状态机复用同一个 axios 传输层.
export async function requestJson(path, body) {
  try {
    const response = body === undefined
      ? await http.get(path)
      : await http.post(path, body ?? {})
    return response.data
  } catch (cause) {
    const error = new Error(errText(cause))
    error.status = cause?.response?.status
    error.payload = cause?.response?.data
    throw error
  }
}

export const api = {
  health: () => http.get('/api/health').then((r) => r.data),
  getMode: () => http.get('/api/mode').then((r) => r.data),
  setMode: (mode) => http.post('/api/mode', { control_mode: mode }).then((r) => r.data),
  listActions: (kind) => http.get('/api/actions', { params: kind ? { kind } : {} }).then((r) => r.data),
  getAction: (name) => http.get(`/api/actions/${name}`).then((r) => r.data),
  saveActionDescription: (name, desc) =>
    http.put(`/api/actions/${name}/description`, { desc }).then((r) => r.data),
  saveActionLabel: (name, label) =>
    http.put(`/api/actions/${name}/label`, { label }).then((r) => r.data),
  deleteAction: (name) => http.delete(`/api/actions/${name}`).then((r) => r.data),
  // 动作 YAML 源文件 (整文件读写; 保存后端全量校验通过即热重载)
  getActionRaw: (name) => http.get(`/api/actions/${name}/raw`).then((r) => r.data),
  saveActionRaw: (name, text) => http.put(`/api/actions/${name}/raw`, { text }).then((r) => r.data),
  reloadActions: () => http.post('/api/actions/reload').then((r) => r.data),
  runAction: (name, params, mode) =>
    http.post(`/api/actions/${name}/run`, { params, mode }).then((r) => r.data),
  // 设备资源表 + 实时占用 (流程编辑器选资源 / 占用诊断)
  listResources: () => http.get('/api/resources').then((r) => r.data),
  // 机器人便捷端点 (维护页低延迟点动)
  jogStart: (axisId) => http.post('/api/robot/jog/start', { axis_id: axisId }).then((r) => r.data),
  jogStop: () => http.post('/api/robot/jog/stop', {}).then((r) => r.data),
  step: (axis, distance, motion) =>
    http.post('/api/robot/step', { axis, distance, motion }).then((r) => r.data),
  robotStop: () => http.post('/api/robot/stop', {}).then((r) => r.data),
  robotEmergencyStop: (pressed) => http.post('/api/robot/emergency_stop', { pressed }).then((r) => r.data),
  robotEnable: () => http.post('/api/robot/enable', {}).then((r) => r.data),
  robotDisable: () => http.post('/api/robot/disable', {}).then((r) => r.data),
  // confirm=true = 已人工确认无其他控制者, 后端先清 CurrentCommandId 接管守卫再重连
  robotConnect: (confirm = false) =>
    http.post('/api/robot/connect', confirm ? { confirm: true } : {}).then((r) => r.data),
  robotClearError: () => http.post('/api/robot/clear_error', {}).then((r) => r.data),
  robotSetSpeedFactor: (ratio) => http.post('/api/robot/speed_factor', { ratio }).then((r) => r.data),
  // 单点控制 (PC Manual Mode): 复刻 HMI 手动屏的执行器电平二态 + 轴点动
  // 会话: enter 需 DEBUG + 全局空闲; exit / jog stop / axis stop 是安全方向, 不限模式
  // 方法名保留 pcManual 前缀: 历史上孔板标定的"去使能手推"占用过 manualEnter/manualExit,
  // 那套已废弃删除, 但前缀是现成的语义标识 (PC 单点 vs 柜面手动档), 继续沿用。
  pcManualEnter: () => http.post('/api/manual/session/enter', {}).then((r) => r.data),
  pcManualExit: () => http.post('/api/manual/session/exit', {}).then((r) => r.data),
  pcManualKeepalive: () => http.post('/api/manual/session/keepalive', {}).then((r) => r.data),
  pcManualPoints: (station) =>
    http.get('/api/manual/points', { params: station ? { station } : {} }).then((r) => r.data),
  pcManualState: (station) =>
    http.get('/api/manual/state', { params: station ? { station } : {} }).then((r) => r.data),
  pcManualCylinder: (id, on) => http.post(`/api/manual/cylinder/${id}`, { on }).then((r) => r.data),
  pcManualJogStart: (id, direction) =>
    http.post(`/api/manual/axis/${id}/jog/start`, { direction }).then((r) => r.data),
  pcManualJogKeep: (id) => http.post(`/api/manual/axis/${id}/jog/keep`, {}).then((r) => r.data),
  pcManualJogStop: (id) => http.post(`/api/manual/axis/${id}/jog/stop`, {}).then((r) => r.data),
  pcManualAxisHome: (id) => http.post(`/api/manual/axis/${id}/home`, {}).then((r) => r.data),
  pcManualAxisStop: (id) => http.post(`/api/manual/axis/${id}/stop`, {}).then((r) => r.data),
  pcManualAxisReset: (id) => http.post(`/api/manual/axis/${id}/reset`, {}).then((r) => r.data),
  pcManualAxisMove: (id, mode, target, vel) =>
    http.post(`/api/manual/axis/${id}/move`, { mode, target, vel }).then((r) => r.data),
  pcManualHomeAll: () => http.post('/api/manual/home_all', { confirm: true }).then((r) => r.data),
  // 设备状态机启停 (脉冲 PLCStop/PLCStart, 与柜面按钮并联): 单点模式要求非运行态,
  // 有这两个就不必跑去柜子按停止/启动
  pcManualMachineStop: () => http.post('/api/manual/machine/stop', { confirm: true }).then((r) => r.data),
  pcManualMachineResume: () => http.post('/api/manual/machine/resume', { confirm: true }).then((r) => r.data),
  // 三维工程 authoring: 读取始终开放, 写回和重建由后端 DEBUG 门禁统一裁决.
  threeDAuthoringStatus: () => http.get('/api/3d/authoring/status').then((r) => r.data),
  threeDRead: (body) => http.post('/api/3d/authoring/read', body).then((r) => r.data),
  threeDWrite: (body) => http.post('/api/3d/authoring/write', body).then((r) => r.data),
  threeDListClips: () => http.get('/api/3d/authoring/clips').then((r) => r.data),
  // flow 可选: {operation, inputs} = 只编这一条流程并用这组入参(约 20 秒); 不传就是原样全量
  threeDStartRebuild: (only, flow) => http.post('/api/3d/authoring/rebuild', {
    only: only || [], ...(flow ? { flow } : {}),
  }).then((r) => r.data),
  threeDRebuildStatus: () => http.get('/api/3d/authoring/rebuild/status').then((r) => r.data),
  // PALLASVision Bridge (仅通讯重连, 不触发拍照/运动)
  pallasStatus: () => http.get('/api/pallas/status').then((r) => r.data),
  pallasReconnect: () => http.post('/api/pallas/reconnect', {}).then((r) => r.data),
  // 脚本仓库 (action/operation 节点树)
  listWorkspaces: () => http.get('/api/scripts/workspaces').then((r) => r.data),
  listScripts: (kind, ws = 'default') =>
    http.get('/api/scripts', { params: kind ? { ws, kind } : { ws } }).then((r) => r.data),
  getScript: (name, ws = 'default') =>
    http.get(`/api/scripts/${name}`, { params: { ws } }).then((r) => r.data),
  createScript: (name, kind, label, group, ws = 'default') =>
    http.post('/api/scripts', { name, kind, label, group }, { params: { ws } }).then((r) => r.data),
  saveScript: (name, doc, ws = 'default') =>
    http.put(`/api/scripts/${name}`, { doc }, { params: { ws } }).then((r) => r.data),
  deleteScript: (name, ws = 'default') =>
    http.delete(`/api/scripts/${name}`, { params: { ws } }).then((r) => r.data),
  cloneScript: (name, dst, ws = 'default') =>
    http.post(`/api/scripts/${name}/clone`, { dst }, { params: { ws } }).then((r) => r.data),
  renameScript: (name, dst, ws = 'default') =>
    http.post(`/api/scripts/${name}/rename`, { dst }, { params: { ws } }).then((r) => r.data),
  setScriptLabel: (name, label, ws = 'default') =>
    http.post(`/api/scripts/${name}/label`, { label }, { params: { ws } }).then((r) => r.data),
  listScriptVersions: (name, ws = 'default') =>
    http.get(`/api/scripts/${name}/versions`, { params: { ws } }).then((r) => r.data),
  getScriptVersion: (name, rev, ws = 'default') =>
    http.get(`/api/scripts/${name}/versions/${rev}`, { params: { ws } }).then((r) => r.data),
  // VM 运行 / 调试
  getKnobs: (name, ws = 'default') =>
    http.get(`/api/scripts/${name}/debug/knobs`, { params: { ws } }).then((r) => r.data),
  debugRun: (name, inputs, mode, modeRun = 'run', startAid = '', overrides = {}, ws = 'default') =>
    http.post(`/api/scripts/${name}/debug/run`, { inputs: inputs || {}, mode, mode_run: modeRun, start_aid: startAid || null, overrides: overrides || {} }, { params: { ws } }).then((r) => r.data),
  debugStep: (runId) => http.post(`/api/debug/${runId}/step`).then((r) => r.data),
  debugStepOver: (runId) => http.post(`/api/debug/${runId}/step_over`).then((r) => r.data),
  debugContinue: (runId) => http.post(`/api/debug/${runId}/run`).then((r) => r.data),
  debugPause: (runId) => http.post(`/api/debug/${runId}/pause`).then((r) => r.data),
  debugResume: (runId) => http.post(`/api/debug/${runId}/resume`).then((r) => r.data),
  debugStopAfter: (runId) => http.post(`/api/debug/${runId}/stop_after`).then((r) => r.data),
  debugTerminate: (runId) => http.post(`/api/debug/${runId}/terminate`).then((r) => r.data),
  debugEstop: (runId) => http.post(`/api/debug/${runId}/estop`).then((r) => r.data),
  debugStop: (runId) => http.post(`/api/debug/${runId}/stop`).then((r) => r.data),
  debugReset: (runId, aid) => http.post(`/api/debug/${runId}/reset`, { aid: aid || null }).then((r) => r.data),
  debugState: (runId) => http.get(`/api/debug/${runId}/state`).then((r) => r.data),
  debugVars: (runId) => http.get(`/api/debug/${runId}/vars`).then((r) => r.data),
  setBreakpoints: (runId, aids) => http.post(`/api/debug/${runId}/breakpoints`, { aids }).then((r) => r.data),
  hitlReply: (runId, reqId, payload) => http.post(`/api/debug/${runId}/human/${reqId}`, payload).then((r) => r.data),
  debugActive: () => http.get('/api/debug/active').then((r) => r.data),
  // 设备节点 (健康 + 快照)
  listNodes: () => http.get('/api/nodes').then((r) => r.data),
  getNode: (id) => http.get(`/api/nodes/${id}`).then((r) => r.data),
  // 执行历史 (运行记录 + 回放)
  listRuns: (params) => http.get('/api/runs', { params: params || {} }).then((r) => r.data),
  getRun: (runId) => http.get(`/api/runs/${runId}`).then((r) => r.data),
  // 排程只读统计 (甘特图数据; window = 每流程取最近 N 次 DONE 的平均)
  plannerStats: (window) =>
    http.get('/api/planner/stats', { params: { window } }).then((r) => r.data),
  plannerTimeline: (name, window) =>
    http.get(`/api/planner/operations/${encodeURIComponent(name)}/timeline`, { params: { window } }).then((r) => r.data),
  // 清除耗时记录 = 把统计基线设到当前时刻 (不删运行记录); operation 为 null 即全部流程
  plannerSetBaseline: (operation) =>
    http.post('/api/planner/baseline', { operation }).then((r) => r.data),
  // 撤销基线, 恢复历史统计; operation 为 null 即清空全部基线
  plannerClearBaseline: (operation) =>
    http.delete('/api/planner/baseline', { params: operation ? { operation } : {} }).then((r) => r.data),
  // 并行实验调度 (批次/样品/段作业; 后端 api/scheduler_routes.py)
  listRecipes: () => http.get('/api/recipes').then((r) => r.data.recipes),
  validateRecipe: (name) => http.get(`/api/recipes/${encodeURIComponent(name)}/validate`).then((r) => r.data),
  // 调度方案编辑 (两条对等路: doc=图形化画布主路, raw=文本页签保 # 注释)
  // 保存两路同守卫: 校验通过才落盘, name 不符 400, 被未完结批次引用 409
  getRecipeDoc: (name) => http.get(`/api/recipes/${encodeURIComponent(name)}/doc`).then((r) => r.data),
  saveRecipeDoc: (name, doc) => http.put(`/api/recipes/${encodeURIComponent(name)}/doc`, { doc }).then((r) => r.data),
  getRecipeRaw: (name) => http.get(`/api/recipes/${encodeURIComponent(name)}/raw`).then((r) => r.data),
  saveRecipeRaw: (name, text) => http.put(`/api/recipes/${encodeURIComponent(name)}/raw`, { text }).then((r) => r.data),
  validateRecipeText: (text) => http.post('/api/recipes/validate', { text }).then((r) => r.data),
  validateRecipeDoc: (doc) => http.post('/api/recipes/validate', { doc }).then((r) => r.data),
  schedulerSnapshot: () => http.get('/api/scheduler/snapshot').then((r) => r.data),
  submitExperiment: (payload) => http.post('/api/experiments', payload).then((r) => r.data),
  listExperiments: (params) => http.get('/api/experiments', { params: params || {} }).then((r) => r.data.batches),
  getExperiment: (bid) => http.get(`/api/experiments/${encodeURIComponent(bid)}`).then((r) => r.data),
  experimentVerb: (bid, verb) =>
    http.post(`/api/experiments/${encodeURIComponent(bid)}/${verb}`, {}).then((r) => r.data),
  experimentReconcile: (bid, payload) =>
    http.post(`/api/experiments/${encodeURIComponent(bid)}/reconcile`, payload || {}).then((r) => r.data),
  sampleVerb: (bid, sid, verb) =>
    http.post(`/api/experiments/${encodeURIComponent(bid)}/samples/${encodeURIComponent(sid)}/${verb}`, {}).then((r) => r.data),
  jobVerb: (bid, sid, flow, verb, body) =>
    http.post(`/api/experiments/${encodeURIComponent(bid)}/samples/${encodeURIComponent(sid)}/jobs/${encodeURIComponent(flow)}/${verb}`, body || {}).then((r) => r.data),
  experimentResults: (bid, sampleId) =>
    http.get(`/api/experiments/${encodeURIComponent(bid)}/results`, { params: sampleId ? { sample_id: sampleId } : {} }).then((r) => r.data.results),
  experimentTimeline: (bid) =>
    http.get(`/api/experiments/${encodeURIComponent(bid)}/timeline`).then((r) => r.data),
  // 物料账本 (货架 板x孔 二态余量 + 中转占用); 建议式, 只预填输入框不参与执行决策
  getMaterials: () => http.get('/api/materials').then((r) => r.data),

  // -- 状态录像 (3D DVR): 时间线回放的数据源 --------------------------------
  recordingStatus: () => http.get('/api/recording/status').then((r) => r.data),
  recordingCoverage: () => http.get('/api/recording/coverage').then((r) => r.data),
  recordingSessions: (params) =>
    http.get('/api/recording/sessions', { params: params || {} }).then((r) => r.data),
  recordingTimeline: (params) =>
    http.get('/api/recording/timeline', { params }).then((r) => r.data),
  recordingMarkers: (params) =>
    http.get('/api/recording/markers', { params }).then((r) => r.data),
  recordingStateAt: (params) =>
    http.get('/api/recording/state_at', { params }).then((r) => r.data),
  // 增量事件历史: 关键帧里没有的派生态(板在谁手里/托盘挂载/夹爪持握)靠它重放出来
  recordingHistory: (params) =>
    http.get('/api/recording/history', { params }).then((r) => r.data),
  recordingFrames: (params) =>
    http.get('/api/recording/frames', { params }).then((r) => r.data),
  recordingActions: (params) =>
    http.get('/api/recording/actions', { params }).then((r) => r.data),
  recordingReconcile: (params) =>
    http.post('/api/recording/reconcile', null, { params: params || {} }).then((r) => r.data),
  // 物料树 (每类的位置与传感器); 左侧导航与页面分区据此渲染, 前端不硬编码分类
  getMaterialTopology: () => http.get('/api/materials/topology').then((r) => r.data.categories),
  getMaterialNext: (kind) => http.get('/api/materials/next', { params: { kind } }).then((r) => r.data),
  // 某脚本输入框的预填建议: 该填哪个库位/孔号由后端按绑定表解析, 前端不做推断
  suggestMaterialInputs: (script, varNames) =>
    http.get('/api/materials/suggest', { params: { script, vars: (varNames || []).join(',') } })
      .then((r) => r.data),
  getMaterialEvents: (params) => http.get('/api/materials/events', { params }).then((r) => r.data.events),
  markMaterial: (body) => http.post('/api/materials/mark', body).then((r) => r.data),
  setMaterialStaging: (area, plate) =>
    http.post('/api/materials/staging', { area, plate }).then((r) => r.data),
  // 人工清在途: 流程中途取消/断电后板滞留在夹爪上时用。
  // landAt: '' 只清行 (去向不明) | 'rack' 记回原库位 | 'staging' 记入中转区
  clearMaterialTransit: (carrier, landAt = '') =>
    http.post('/api/materials/transit', { carrier, land_at: landAt }).then((r) => r.data),
  // 货架库位板级在架人工账 (货架光电无信号, 有板/无板只能人工记; 无板参与决策过滤)
  setMaterialRack: (kind, plate, present) =>
    http.post('/api/materials/rack', { kind, plate, present }).then((r) => r.data),
  // 单板停放位 (点样座/刮板拍照台) 有板/无板人工账: 这两处无在位传感器, 只能人工记。
  // ⚠ 只供展示与人工同步, 不进流程判断 (流程内的板位权威仍是调度器 samples.position)
  setMaterialSeat: (seat, present) =>
    http.post('/api/materials/seat', { seat, present }).then((r) => r.data),
  setMaterialMagazine: (magazine, count) =>
    http.post('/api/materials/magazine', { magazine, count }).then((r) => r.data),
  setMaterialBottle: (bottle, volumeMl) =>
    http.post('/api/materials/bottle', { bottle, volume_ml: volumeMl }).then((r) => r.data),
  // 光电对账: 读 PLC 12 位料库检测与账本比对 (只报不改); PLC 断链/符号未发布时 503
  reconcileMaterials: () => http.post('/api/materials/reconcile').then((r) => r.data),
  // 单件内容物人工盘点 (粉 mm³ / 液 mL / 已淋洗); 缺省字段不动, 试机假数据由人覆盖式改回
  setMaterialCellAmount: (kind, plate, hole, fields) =>
    http.post('/api/materials/cell_amount', { kind, plate, hole, ...fields }).then((r) => r.data),
  // 工位座人工盘点: identity 省略=清账 (去向不明不猜); 给 {kind, plate, hole}=放件
  setMaterialPayloadSeat: (seat, identity = null) =>
    http.post('/api/materials/payload_seat', identity ? { seat, ...identity } : { seat }).then((r) => r.data),
  // 一键审查 (账实体检, 只报不改): 四组核对行 + 计数徽标 + 原始字节 + 账本快照
  auditMaterials: () => http.post('/api/materials/audit').then((r) => r.data),
  // 释放某样品的物料预留 (审查"孤儿预留"行的一键修复; 幂等)
  releaseMaterialReservation: (sampleId, kind = null) =>
    http.post('/api/materials/reservations/release', { sample_id: sampleId, kind }).then((r) => r.data),
  // 升降板仓行程标定 (多点最小二乘拟合空仓位 + 堆叠节距); 未标定时 feedlift.probe_stack 拒动作。
  // ⚠ 下面两个 POST 会驱动 1Z/2Z 升降轴运动 (后端经执行器发对应光电搜索动作), 不是纯读。
  getFeedliftCalib: () => http.get('/api/feedlift/calib').then((r) => r.data),
  calibFeedliftSample: (magazine, plates) =>
    http.post('/api/feedlift/calib/sample', { magazine, plates }).then((r) => r.data),
  clearFeedliftSamples: (magazine) =>
    http.delete('/api/feedlift/calib/samples', { params: { magazine } }).then((r) => r.data),
  measureFeedlift: (magazine) =>
    http.post('/api/feedlift/measure', { magazine }).then((r) => r.data),
  // 统一点位目录 (机器人 / PLC伺服 / CNC)
  listPoints: () => http.get('/api/points').then((r) => r.data),
  getPointsTree: () => http.get('/api/points').then((r) => r.data),
  listPointGrids: () => http.get('/api/points/grids').then((r) => r.data.grids),
  getPoint: (category, id) =>
    http.get(`/api/points/${category}/${encodeURIComponent(id)}`).then((r) => r.data),
  listPointsRawFiles: () => http.get('/api/points/raw/files').then((r) => r.data.files),
  getPointsRaw: (kind) => http.get('/api/points/raw', { params: { kind } }).then((r) => r.data),
  savePointsRaw: (kind, text) =>
    http.put('/api/points/raw', { text }, { params: { kind } }).then((r) => r.data),
  // 单点原始片段 (机器人): 只看/改当前点对应的源条目
  getPointRaw: (category, id) =>
    http.get(`/api/points/${category}/${encodeURIComponent(id)}/raw`).then((r) => r.data),
  savePointRaw: (category, id, text) =>
    http.put(`/api/points/${category}/${encodeURIComponent(id)}/raw`, { text }).then((r) => r.data),
  captureRobotPoint: (id) =>
    http.post(`/api/points/robot/${encodeURIComponent(id)}/capture`, {}).then((r) => r.data),
  commitRobotPoint: (id, payload) =>
    http.post(`/api/points/robot/${encodeURIComponent(id)}/commit`, payload).then((r) => r.data),
  // 示教复核 (teach-verify): 用新采集位姿重算进近航点 / 逐点验证走位 / 回位漂移检查
  // (capture/commit 复用上面 captureRobotPoint/commitRobotPoint, 同 /capture、/commit 端点, 不重复)
  teachPlan: (id, capturedPose) =>
    http.post(`/api/points/robot/${encodeURIComponent(id)}/teach/plan`, { captured_pose: capturedPose }).then((r) => r.data),
  teachMove: (id, pose, motion) =>
    http.post(`/api/points/robot/${encodeURIComponent(id)}/teach/move`, { pose, motion }).then((r) => r.data),
  teachDrift: (id, capturedPose) =>
    http.post(`/api/points/robot/${encodeURIComponent(id)}/teach/drift`, { captured_pose: capturedPose }).then((r) => r.data),
  // PC 侧 flat 目标点位 (点样/拍照): 读 actpos 镜像 / 存 value / 下发 *_Target
  getTargetActpos: (key) =>
    http.get(`/api/points/plc_servo_target/${encodeURIComponent(key)}/actpos`).then((r) => r.data),
  setTargetValue: (key, value) =>
    http.put(`/api/points/plc_servo_target/${encodeURIComponent(key)}/value`, { value }).then((r) => r.data),
  pushTarget: (key) =>
    http.post(`/api/points/plc_servo_target/${encodeURIComponent(key)}/push`).then((r) => r.data),
  // 组合点位 (多轴聚合, 如点样位置): 逐成员读 actpos / 存 value, 整体下发各成员 *_Target
  getCompositeMemberActpos: (key, member) =>
    http.get(`/api/points/plc_servo_composite/${encodeURIComponent(key)}/member/${encodeURIComponent(member)}/actpos`).then((r) => r.data),
  setCompositeMemberValue: (key, member, value) =>
    http.put(`/api/points/plc_servo_composite/${encodeURIComponent(key)}/member/${encodeURIComponent(member)}/value`, { value }).then((r) => r.data),
  pushComposite: (key) =>
    http.post(`/api/points/plc_servo_composite/${encodeURIComponent(key)}/push`).then((r) => r.data),
  // plc_servo 离散召回位 PC 真源 value (收编工位, 如地轨)
  setServoValue: (key, value) =>
    http.put(`/api/points/plc_servo/${encodeURIComponent(key)}/value`, { value }).then((r) => r.data),
  // 双源同步对账 (收编工位): diff 只读 / push 下发真源+同步面板 / pull 回收示教 (confirm 二次确认)
  syncDiff: (workstation, threshold) =>
    http.get(`/api/points/sync/${encodeURIComponent(workstation)}/diff`,
      threshold == null ? undefined : { params: { threshold } }).then((r) => r.data),
  syncPush: (workstation) =>
    http.post(`/api/points/sync/${encodeURIComponent(workstation)}/push`).then((r) => r.data),
  syncPull: (workstation, confirm) =>
    http.post(`/api/points/sync/${encodeURIComponent(workstation)}/pull`, { confirm }).then((r) => r.data),
  // 孔板标定 / 按孔下发
  listCalibInstances: () => http.get('/api/calibration/instances').then((r) => r.data),
  listPlateTypes: () => http.get('/api/calibration/plate_types').then((r) => r.data),
  getCalibInstance: (id) =>
    http.get(`/api/calibration/${encodeURIComponent(id)}`).then((r) => r.data),
  getCalibTargets: (id) =>
    http.get(`/api/calibration/${encodeURIComponent(id)}/targets`).then((r) => r.data),
  readActpos: () => http.get('/api/calibration/actpos').then((r) => r.data),
  captureWell: (id, row, col) =>
    http.post(`/api/calibration/${encodeURIComponent(id)}/capture`, { row, col }).then((r) => r.data),
  commitCalibration: (id, points) =>
    http.post(`/api/calibration/${encodeURIComponent(id)}/commit`, { points }).then((r) => r.data),
  pushWell: (id, row, col) =>
    http.post(`/api/calibration/${encodeURIComponent(id)}/push`, { row, col }).then((r) => r.data),
  // 注: 曾经的「去使能手推」(manualState/manualEnter/manualExit → /api/calibration/manual/*)
  // 已删除 —— PLC 侧那条路是自毁循环, 详见 components/CalibratePanel.vue 顶部注释。
  // 标定的对点改走上面的 pcManual* 电动点动, 使能状态从 pcManualState 的逐轴 bEnabled 看。
  // 板位对位: 点样视觉零点一键示教 (.163 对位相机; teach 会走机器人取板到 P86, 请求较久)
  plateAlignStatus: () => http.get('/api/plate_align/status').then((r) => r.data),
  plateAlignTeach: () => http.post('/api/plate_align/teach', {}).then((r) => r.data),
  plateAlignApply: (u, v, theta, confirm) =>
    http.post('/api/plate_align/apply', { u, v, theta, confirm }).then((r) => r.data),
  // 刮板对刀: 三轴实读 + gcode 标定 → Δ/检查高度/建议 plate_origin (与 align_readout 动作同产地)
  alignReadout: () => http.get('/api/photoscrape/align_readout').then((r) => r.data),
  // 刮痕标定: 构造第 N 轮标定工作区 (图案几何/差分基准帧由后端 scrape_calib 单点决定)
  calibPattern: (sampleId, round) =>
    http.post('/api/photoscrape/calib_pattern', { sample_id: sampleId, round }).then((r) => r.data),
  // 刮痕测量: 指令 vs 实刮位置误差 + 可信度判据 + 建议 plate_origin
  scrapeOffset: (summaryPath, searchMarginCm) =>
    http.post('/api/photoscrape/scrape_offset', { summary_path: summaryPath, search_margin_cm: searchMarginCm })
      .then((r) => r.data),
  // 设备参数 (app.yaml camera/gcode/vision 段)
  getConfigSection: (section) => http.get(`/api/config/${section}`).then((r) => r.data),
  saveConfigSection: (section, values) =>
    http.put(`/api/config/${section}`, { values }).then((r) => r.data),
  // PLC 程序 (CODESYS POU) 编辑/编译: 后端经文件 IPC 驱动 InoProShop; 首次调用冷启动 IDE (较慢)
  plcStatus: () => http.get('/api/plc/status').then((r) => r.data),
  plcSession: () => http.get('/api/plc/session').then((r) => r.data),
  plcSessionTakeover: (reason) =>
    http.post('/api/plc/session/takeover', { by: 'operator', reason: reason || 'upper UI takeover' }).then((r) => r.data),
  plcSessionRelease: () => http.post('/api/plc/session/release', { by: 'operator' }).then((r) => r.data),
  listPous: () => http.get('/api/plc/pous').then((r) => r.data),
  // POU 用 path (如 Application/收集流程) 定位, 含斜杠故走 query/body 参数
  getPou: (path) => http.get('/api/plc/pou', { params: { path } }).then((r) => r.data),
  savePou: (path, body) => http.put('/api/plc/pou', { path, ...body }).then((r) => r.data),
  compilePou: () => http.post('/api/plc/compile', {}).then((r) => r.data),
  // OPC 符号导出 (pragma 管理): 列出某 GVL 变量及导出态 / 切换某变量导出 (改后需编译+下载生效)
  plcListSymbols: (path) => http.get('/api/plc/symbols', { params: { path } }).then((r) => r.data),
  plcSetSymbol: (path, name, enabled) =>
    http.post('/api/plc/symbols', { path, name, enabled }).then((r) => r.data),
  // 部署 (全下载到真机; allow_deploy=false 时后端 403): 编译与安全停机握手通过后下载，自动启动并等待 PLC Ready
  plcOnlineStatus: () => http.get('/api/plc/online_status').then((r) => r.data),
  plcDeployStatus: () => http.get('/api/plc/deploy/status').then((r) => r.data),
  plcDeployReconcile: (operatorConfirmedOnlineVersion) => http.post('/api/plc/deploy/reconcile', {
    operator_confirmed_online_version: operatorConfirmedOnlineVersion === true,
  }).then((r) => r.data),
  plcDeploy: () => http.post('/api/plc/deploy', {}).then((r) => r.data),
  // .project 全量版本: 列表 / 手动快照 / 还原; 下载走浏览器直链 (二进制, 经 Vite /api 代理)
  plcVersions: () => http.get('/api/plc/versions').then((r) => r.data),
  plcSnapshot: (message) => http.post('/api/plc/versions/snapshot', { message: message || '' }).then((r) => r.data),
  plcRestore: (rev) => http.post(`/api/plc/versions/${encodeURIComponent(rev)}/restore`, {}).then((r) => r.data),
  plcVersionDownloadUrl: (rev) => `/api/plc/versions/${encodeURIComponent(rev)}/download`,
  // 工位 L2 复位 (清故障): 由「设备」页工位节点调用 (执行→动作页, 状态→设备页遥测)
  plcStationReset: (station) =>
    http.post(`/api/plc/stations/${encodeURIComponent(station)}/reset`, {}).then((r) => r.data),
  // 工位初始化: 跑该工位 *.init 原子 (与复位是两件事 —— 复位只清故障位不动机构)。
  // 返回 {station, action, ok, results:[DTO]}; 展缸逐缸跑故 results 有 8 条, 其余工位 1 条。
  plcStationInit: (station) =>
    http.post(`/api/plc/stations/${encodeURIComponent(station)}/init`, {}).then((r) => r.data),
  // 全工站一键初始化: 走 system_init_all 编排 (留痕可回放); 某站失败整体 422 并在 detail 里点名
  plcStationsInitAll: () => http.post('/api/plc/stations/init_all', {}).then((r) => r.data),
  // 液位检测外设 (香橙派): 只读快照 + 命令透传 (视频经 wlFrameUrl 单帧轮询直挂 <img>)
  wlSnapshot: () => http.get('/api/water_level/snapshot').then((r) => r.data),
  wlCmd: (cmd, payload) => http.post(`/api/water_level/cmd/${cmd}`, payload || {}).then((r) => r.data),
  // 「识别」页走势曲线: 单通道 percent/front% 历史 (独立端点, 不并进 1s 轮询的 snapshot)
  wlHistory: (channel, limit) =>
    http.get(`/api/water_level/history/${channel}`, { params: limit ? { limit } : undefined })
      .then((r) => r.data),
  // 视觉调试台: 固定工作区 Before/After 拍照、上传和双帧分析
  getVisionDebugState: () => http.get('/api/vision/debug/state').then((r) => r.data),
  captureVisionDebug: (role, params) => http.post('/api/vision/debug/capture', {
    role,
    exposure_time_us: params?.exposure_time_us,
    gain: params?.gain,
    uv_on_time_ms: params?.uv_on_time_ms,
  }).then((r) => r.data),
  uploadVisionDebug: (role, file) => {
    const fd = new FormData()
    fd.append('file', file)
    return http.post(`/api/vision/debug/upload/${role}`, fd).then((r) => r.data)
  },
  analyzeVisionDebug: (params) => http.post('/api/vision/debug/analyze', {
    image_plate_orientation: params?.image_plate_orientation,
    auto_rectify_tilt: params?.auto_rectify_tilt,
    rectify_min_angle_deg: params?.rectify_min_angle_deg,
    min_row_score: params?.min_row_score,
    image_plate_rotation_deg: params?.image_plate_rotation_deg ?? null,
  }).then((r) => r.data),
  previewVisionDebugCnc: (bandId) =>
    http.post('/api/vision/debug/cnc_preview', { band_id: bandId }).then((r) => r.data),
  // 把调试台当前识别参数写回 config.vision 单一真源 (生产 analyze 实时读取, 下次即生效)
  applyVisionToProduction: () =>
    http.post('/api/vision/debug/apply_to_production').then((r) => r.data),
  // 载入生产 case 复盘调参: 列 vision_output 下含 inputs.json 的 case / 把其 before+after 拷入调试台
  listVisionDebugCases: () => http.get('/api/vision/debug/cases').then((r) => r.data),
  loadVisionDebugCase: (summaryDir) =>
    http.post('/api/vision/debug/load_case', { summary_dir: summaryDir }).then((r) => r.data),
  // 拍照刮板手绘路径来源 (视觉失败兜底门): 板参照 / 预览(所见即所跑) / 提交落 summary
  getSketchContext: (summaryPath) =>
    http.get('/api/photoscrape/sketch_context', { params: { summary_path: summaryPath } }).then((r) => r.data),
  previewScrapePath: (payload) => http.post('/api/photoscrape/preview_path', payload).then((r) => r.data),
  commitSketch: (payload) => http.post('/api/photoscrape/sketch_commit', payload).then((r) => r.data),
  // 4 角标板 → 后端出透视矫正帧(主路径): 返回全幅 plate_bbox_px + manual_rectify(C-2); 失败前端回落单应老路
  rectifySketch: (payload) => http.post('/api/photoscrape/sketch_rectify', payload).then((r) => r.data),
  // 门内"重新识别(调参)": 用调整后的识别参数在本 run before/after 重跑, 返回同形结果(含 bands)
  reanalyzePhotoscrape: (payload) => http.post('/api/photoscrape/reanalyze', payload).then((r) => r.data),
  // 香橙派 SSH 远程管理: 启动/停止 run.sh + 查进程状态
  wlOpiStart: (wait) =>
    http.post(`/api/water_level/opi/start${wait ? '?wait=1' : ''}`).then((r) => r.data),
  wlOpiStop: () => http.post('/api/water_level/opi/stop').then((r) => r.data),
  wlOpiStatus: () => http.get('/api/water_level/opi/status').then((r) => r.data),
  wlOpiDeploy: () => http.post('/api/water_level/opi/deploy').then((r) => r.data),
}

// 单帧 JPEG URL (同源, 经 vite 代理到后端再代理香橙派): path=ch1。网格总览与单路实时统一用它
// 低频轮询 (瞬时连接, 完成即释放), 不占持久连接 —— 避开旧持久 MJPEG 流"瞬态停帧后永久冻结"。
export function wlFrameUrl(path) {
  return `/api/water_level/frame/${path}`
}

// 检测叠加图 URL (「识别」页): 上位机现渲, 非代理 —— ROI 框 + 湿区掩膜 + 前沿线 + 数值 HUD。
// 图源与 snapshot 数字同出一帧, 故随检测周期 (~2s) 更新, 比原始帧慢但与读数严格对应。
// overlay=false 关掉就地涂色与前沿线, 只留标定框与 HUD (供对照看算法判得准不准)。
export function wlDebugFrameUrl(path, overlay = true) {
  return `/api/water_level/debug_frame/${path}?overlay=${overlay ? 1 : 0}`
}

// axios 错误信息提取: 优先 FastAPI 的 detail, 否则回退到错误字符串
// (集中一处, 后端错误结构变更时只需改这里; 行为与各处原内联逻辑等价)
export function errText(e) {
  return (e && e.response && e.response.data && e.response.data.detail) || String(e)
}

// WebSocket 事件流 URL (经 vite 代理到后端)
export function eventsWsUrl() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  return `${proto}://${location.host}/api/ws/events`
}
