/**
 * 功能: 实时页板面痕迹的纯逻辑层 —— 工艺阶段推导与痕迹几何构造, 零 three 依赖.
 *
 * 分工: 本模块只回答两个问题 ——
 *   1. "这块板走到哪个工艺阶段了"(stageFromJobs): 从调度器快照每样品的 jobs[]
 *      (script + status)推导, 是权威作业账的**只读投影**, 不维护第二套账本
 *      (PTLC_REALTIME_PROTOCOL §5);
 *   2. "该画什么痕迹"(spotBandRegion / wetRegion / …): 把标定与显式假设构造成
 *      与编译器 compiled.spotRegions / wetRegions **同形**的声明, 下游共用
 *      PlateStage/PlateBinding 一致的 UV 换算与绘制链。
 *
 * 数据从哪来:
 *   · 标定映射: action-motion-map.json 的 spotBandCalib / wetFrontTargetCm
 *     (clip_compiler.SPOT_BAND_CALIB 的导出 —— 导映射不导毫米);
 *   · 端点毫米: /api/3d/plate-traces/config 的 spot_pose 示教值(实读点表);
 *   · 实际刀路/谱带: /api/3d/plate-traces/{sample_id}(视觉 case 目录的板 cm 帧真源)。
 */

/** 工艺阶段(按序递进; 位置词表之外的**外观**维度, 不影响任何位置仲裁)。 */
export const STAGE = Object.freeze({
  BLANK: 'blank',
  SPOTTED: 'spotted',
  DEVELOPED: 'developed',
  SCRAPED: 'scraped',
})

const STAGE_RANK = { [STAGE.BLANK]: 0, [STAGE.SPOTTED]: 1, [STAGE.DEVELOPED]: 2, [STAGE.SCRAPED]: 3 }

/**
 * 里程碑表: 某段作业(script)DONE 后, 样品至少到达的阶段。
 *
 * 与配方 serial_v1/parallel_v1 的 script 名对齐(pf_*), 同名单段/周期 operation 一并
 * 收录(手动逐段跑批时 jobs 里出现的是它们)。不在表里的脚本(转移/耗材/拍照等)不改
 * 阶段 —— 阶段只看工艺三大步: 点样 / 展开 / 刮取。
 */
export const STAGE_MILESTONES = Object.freeze({
  pf_s2_spot: STAGE.SPOTTED,
  sampling_execute: STAGE.SPOTTED,
  sampling_multi_execute: STAGE.SPOTTED,
  sampling_cycle: STAGE.SPOTTED,
  sampling_multi_cycle: STAGE.SPOTTED,
  pf_s6_develop_wait: STAGE.DEVELOPED,
  develop_execute: STAGE.DEVELOPED,
  develop_cycle: STAGE.DEVELOPED,
  pf_s9_scrape: STAGE.SCRAPED,
  photoscrape_process: STAGE.SCRAPED,
  photoscrape_cycle: STAGE.SCRAPED,
})

/** 点样类脚本(渐进色带的"正在点样"判据要用)。 */
const SPOTTING_SCRIPTS = new Set(
  Object.keys(STAGE_MILESTONES).filter((key) => STAGE_MILESTONES[key] === STAGE.SPOTTED),
)

/**
 * 功能: 从一个样品的作业列表推导工艺阶段.
 *
 * 判据是 **DONE 的最高里程碑**: 段没跑完(RUNNING/FAILED/PENDING)不算 —— 阶段是
 * "已完成的工艺事实", 不是预告。同时报告"点样段正在跑"(渐进色带的开关)。
 *
 * @param {Array<{script?: string, status?: string}>} jobs 快照里该样品的 jobs[]
 * @returns {{stage: string, spottingRunning: boolean}}
 */
export function stageFromJobs(jobs) {
  let stage = STAGE.BLANK
  let spottingRunning = false
  for (const job of jobs || []) {
    const script = String(job?.script || '')
    const status = String(job?.status || '').toUpperCase()
    const milestone = STAGE_MILESTONES[script]
    if (!milestone) continue
    if (status === 'DONE' && STAGE_RANK[milestone] > STAGE_RANK[stage]) stage = milestone
    if (status === 'RUNNING' && SPOTTING_SCRIPTS.has(script)) spottingRunning = true
  }
  return { stage, spottingRunning }
}

/**
 * 功能: 由标定映射 + 示教毫米构造点样色带 region(与 compiled.spotRegions 的一项同形).
 *
 * ⚠ 本仿射与 clip_compiler._register_spot_region **成对**(一处规则两处实现, 与
 * PLATE_POINT_SLOT ↔ POINT_TO_SLOT 同一条纪律): 改任何一边必须同步另一边,
 * 否则演示片段与实时页会把同一条带画在两个位置, 且没有指标会报。
 *
 * @param {object} calib motion-map 的 spotBandCalib
 * @param {{xStartMm: number, xEndMm: number, yHeightMm: number}} pose spot_pose 示教值
 * @returns {object|null} region; 入参不全时 null(留白)
 */
export function spotBandRegion(calib, pose) {
  if (!calib || !pose) return null
  const numbers = [pose.xStartMm, pose.xEndMm, pose.yHeightMm,
    calib.xOriginMm, calib.yOriginMm, calib.bandHalfCm]
  if (numbers.some((value) => !Number.isFinite(Number(value)))) return null
  const xDir = Number(calib.xDir) < 0 ? -1 : 1
  const yDir = Number(calib.yDir) < 0 ? -1 : 1
  const x0 = ((pose.xStartMm - calib.xOriginMm) / 10) * xDir
  const x1 = ((pose.xEndMm - calib.xOriginMm) / 10) * xDir
  const y = ((pose.yHeightMm - calib.yOriginMm) / 10) * yDir
  const half = Number(calib.bandHalfCm)
  const size = Array.isArray(calib.plateSizeCm) ? calib.plateSizeCm : [20, 20]
  return {
    frame: 'plate-cm',
    plateSizeCm: [Number(size[0]) || 20, Number(size[1]) || 20],
    bands: [{
      bandCm: [Math.min(x0, x1), y - half, Math.max(x0, x1), y + half],
      fill: { axis: 'x', dir: x1 >= x0 ? 1 : -1 },
    }],
    machine: {
      xAxis: calib.machine?.xAxis || 'axis_6x',
      yAxis: calib.machine?.yAxis || 'axis_7y',
      xDir,
      yDir,
    },
  }
}

/**
 * 功能: 构造润湿 region(与 compiled.wetRegions 的一项同形; 缸内板走重力锚定).
 * @param {number} frontTargetCm 前沿目标高度(motion-map 的 wetFrontTargetCm)
 * @param {number[]} [plateSizeCm] 板尺寸
 * @returns {object|null}
 */
export function wetRegion(frontTargetCm, plateSizeCm = [20, 20]) {
  const target = Number(frontTargetCm)
  if (!(target > 0)) return null
  const width = Number(plateSizeCm?.[0]) || 20
  return {
    frame: 'plate-cm',
    plateSizeCm: [width, Number(plateSizeCm?.[1]) || 20],
    bandCm: [0, 0, width, target],
    fill: { axis: 'y', dir: 1 },
    anchor: 'gravity',
  }
}

/**
 * 功能: 由 6X 活轴值算色带的渐进填充(点样段 RUNNING 时逐帧调).
 *
 * 真机是蛇形往返扫(最多 60 程), 轴值来回摆 —— 取**单调最大已扫比例**(与上一帧的
 * max 合并), 表现为"喷头扫过哪儿, 色带长到哪儿", 回程不回退。
 *
 * @param {object} calib motion-map 的 spotBandCalib
 * @param {{xStartMm: number, xEndMm: number}} pose 扫线两端的示教毫米
 * @param {number} axisMm 6X 当前毫米值
 * @param {number} prev 上一帧的填充(0..1)
 * @returns {number} 0..1
 */
export function liveSpotFill(calib, pose, axisMm, prev = 0) {
  const before = Math.min(1, Math.max(0, Number(prev) || 0))
  const mm = Number(axisMm)
  if (!calib || !pose || !Number.isFinite(mm)) return before
  const span = Number(pose.xEndMm) - Number(pose.xStartMm)
  if (!Number.isFinite(span) || Math.abs(span) < 1e-6) return before
  const progress = (mm - Number(pose.xStartMm)) / span
  if (!Number.isFinite(progress)) return before
  return Math.max(before, Math.min(1, Math.max(0, progress)))
}

/**
 * 无视觉数据的废板兜底: 标称刮取区(板 cm bbox), 画**刮松暖灰**不擦除 —— 擦除语义只给
 * 真实数据。与编译器 SCRAPE_DEMO_BAND_CM **同值成对**(那边的注释是出处)。
 */
export const SCRAPED_FALLBACK_BAND_CM = Object.freeze([2.0, 8.0, 18.0, 10.0])

/**
 * 功能: 归一化后端 /api/3d/plate-traces/{sample_id} 的返回.
 *
 * @param {object} facts 后端返回
 * @returns {{found: boolean, bandsCm: number[][], scrapePolylineCm: number[][],
 *            cutterWidthCm: number, plateSizeCm: number[]}|null} 非法/未找到时 null
 */
export function normalizeTraceFacts(facts) {
  if (!facts || facts.found !== true) return null
  const size = Array.isArray(facts.plateSizeCm) && facts.plateSizeCm.length === 2
    ? facts.plateSizeCm.map(Number)
    : [20, 20]
  const bands = (Array.isArray(facts.bandsCm) ? facts.bandsCm : [])
    .filter((box) => Array.isArray(box) && box.length === 4
      && box.every((value) => Number.isFinite(Number(value))))
    .map((box) => box.map(Number))
  const path = (Array.isArray(facts.scrapePolylineCm) ? facts.scrapePolylineCm : [])
    .filter((point) => Array.isArray(point) && point.length === 2
      && point.every((value) => Number.isFinite(Number(value))))
    .map((point) => point.map(Number))
  return {
    found: true,
    bandsCm: bands,
    scrapePolylineCm: path.length >= 2 ? path : [],
    cutterWidthCm: Math.max(0.05, Number(facts.cutterWidthCm) || 0.2),
    plateSizeCm: size,
  }
}
