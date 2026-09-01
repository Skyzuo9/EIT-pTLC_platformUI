/**
 * 功能: 实时板面痕迹的纯逻辑层(plateTraceState) —— 阶段推导与痕迹几何构造.
 *
 * 两条要害:
 *   1. **阶段只认 DONE**: RUNNING/FAILED 段不改阶段 —— 阶段是"已完成的工艺事实"。
 *   2. **仿射与编译器成对**: spotBandRegion 的 mm→cm 与 clip_compiler._register_spot_region
 *      必须逐字同构; 这里用编译产物里实际出现过的数字钉住(x_origin 61.2 / 70→240 →
 *      0.88~17.88), 编译器改了映射而这里没跟上时, 本测会红。
 */
import assert from 'node:assert/strict'
import test from 'node:test'

import {
  SCRAPED_FALLBACK_BAND_CM, STAGE, liveSpotFill, normalizeTraceFacts,
  spotBandRegion, stageFromJobs, wetRegion,
} from '../../src/three-d/twin/bindings/plateTraceState.js'

test('stageFromJobs: DONE 的最高里程碑定阶段, RUNNING 不算', () => {
  assert.equal(stageFromJobs([]).stage, STAGE.BLANK)
  assert.equal(stageFromJobs([{ script: 'pf_s1_load', status: 'DONE' }]).stage, STAGE.BLANK,
    '转移段不是工艺里程碑')
  assert.equal(stageFromJobs([{ script: 'pf_s2_spot', status: 'DONE' }]).stage, STAGE.SPOTTED)
  assert.equal(stageFromJobs([{ script: 'pf_s2_spot', status: 'RUNNING' }]).stage, STAGE.BLANK,
    '正在点样还不算点样后')
  assert.equal(stageFromJobs([
    { script: 'pf_s2_spot', status: 'DONE' },
    { script: 'pf_s6_develop_wait', status: 'DONE' },
  ]).stage, STAGE.DEVELOPED)
  assert.equal(stageFromJobs([
    { script: 'pf_s2_spot', status: 'DONE' },
    { script: 'pf_s6_develop_wait', status: 'DONE' },
    { script: 'pf_s9_scrape', status: 'DONE' },
  ]).stage, STAGE.SCRAPED)
  // 手动逐段跑批: 单段/周期 operation 同样计入
  assert.equal(stageFromJobs([{ script: 'sampling_cycle', status: 'DONE' }]).stage, STAGE.SPOTTED)
  assert.equal(stageFromJobs([{ script: 'develop_cycle', status: 'DONE' }]).stage, STAGE.DEVELOPED)
  assert.equal(stageFromJobs([{ script: 'photoscrape_process', status: 'DONE' }]).stage, STAGE.SCRAPED)
})

test('stageFromJobs: 点样段 RUNNING 时报告 spottingRunning(渐进色带的开关)', () => {
  assert.equal(stageFromJobs([{ script: 'pf_s2_spot', status: 'RUNNING' }]).spottingRunning, true)
  assert.equal(stageFromJobs([{ script: 'pf_s9_scrape', status: 'RUNNING' }]).spottingRunning, false)
  assert.equal(stageFromJobs([{ script: 'pf_s2_spot', status: 'DONE' }]).spottingRunning, false)
})

/** 与编译产物 flow.sampling_execute.yaml 逐字一致的标定与示教值(y 侧 2026-08-07 在景实测定标)。 */
const CALIB = {
  xOriginMm: 61.2, xDir: 1, yOriginMm: 18.4, yDir: -1,
  // 半宽 0.225 = clip_compiler.SPOT_BAND_HALF_CM(2026-08-09 观感减半, 实测值是 0.45)
  bandHalfCm: 0.225, plateSizeCm: [20, 20],
  machine: { xAxis: 'axis_6x', yAxis: 'axis_7y' },
}
const POSE = { xStartMm: 70, xEndMm: 240, yHeightMm: -20 }

test('spotBandRegion: 与编译器仿射成对 —— 70→240@-20 映射到 0.88~17.88 / 3.84±0.225', () => {
  const region = spotBandRegion(CALIB, POSE)
  assert.ok(region)
  const [x0, y0, x1, y1] = region.bands[0].bandCm
  assert.ok(Math.abs(x0 - 0.88) < 1e-9)
  assert.ok(Math.abs(x1 - 17.88) < 1e-9)
  assert.ok(Math.abs(y0 - (3.84 - 0.225)) < 1e-9)
  assert.ok(Math.abs(y1 - (3.84 + 0.225)) < 1e-9)
  assert.deepEqual(region.bands[0].fill, { axis: 'x', dir: 1 })
  assert.equal(region.machine.xAxis, 'axis_6x')
  // 反向扫线(起点在终点右侧)渐现方向随之取反
  assert.equal(spotBandRegion(CALIB, { ...POSE, xStartMm: 240, xEndMm: 70 })
    .bands[0].fill.dir, -1)
  // 配置不全 → null(留白纪律)
  assert.equal(spotBandRegion(null, POSE), null)
  assert.equal(spotBandRegion(CALIB, { xStartMm: 70 }), null)
})

test('wetRegion: 下沿到前沿目标高度, 重力锚定', () => {
  const region = wetRegion(14.7)
  assert.deepEqual(region.bandCm, [0, 0, 20, 14.7])
  assert.deepEqual(region.fill, { axis: 'y', dir: 1 })
  assert.equal(region.anchor, 'gravity')
  assert.equal(wetRegion(0), null)
})

test('liveSpotFill: 单调最大已扫比例, 蛇形回程不回退', () => {
  let fill = 0
  fill = liveSpotFill(CALIB, POSE, 70, fill)
  assert.ok(fill < 1e-9, '起点 0')
  fill = liveSpotFill(CALIB, POSE, 155, fill)
  assert.ok(Math.abs(fill - 0.5) < 1e-9, '中点 0.5')
  fill = liveSpotFill(CALIB, POSE, 100, fill)
  assert.ok(Math.abs(fill - 0.5) < 1e-9, '回程保持最大值')
  fill = liveSpotFill(CALIB, POSE, 240, fill)
  assert.equal(fill, 1, '终点 1')
  assert.equal(liveSpotFill(CALIB, POSE, NaN, 0.3), 0.3, '轴值缺失保持原值')
})

test('normalizeTraceFacts: 过滤脏点/脏框, 未找到返回 null', () => {
  assert.equal(normalizeTraceFacts(null), null)
  assert.equal(normalizeTraceFacts({ found: false }), null)
  const facts = normalizeTraceFacts({
    found: true,
    plateSizeCm: [20, 20],
    bandsCm: [[1, 5, 19, 7.5], [1, 2, 19, 'x']],
    scrapePolylineCm: [[1, 5.4], [19, 5.4], [19, NaN]],
    cutterWidthCm: 0.2,
  })
  assert.equal(facts.bandsCm.length, 1, '脏框被滤掉')
  assert.equal(facts.scrapePolylineCm.length, 2, '脏点被滤掉')
  assert.equal(facts.cutterWidthCm, 0.2)
  // 只剩 1 个有效点不成折线
  const single = normalizeTraceFacts({ found: true, scrapePolylineCm: [[1, 2]] })
  assert.deepEqual(single.scrapePolylineCm, [])
})

test('SCRAPED_FALLBACK_BAND_CM 与编译器 SCRAPE_DEMO_BAND_CM 同值(成对常量)', () => {
  assert.deepEqual([...SCRAPED_FALLBACK_BAND_CM], [2.0, 8.0, 18.0, 10.0])
})
