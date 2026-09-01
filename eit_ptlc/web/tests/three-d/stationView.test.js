/**
 * 功能: 模块视角(stations[].camera)的保存判据与定点写回.
 *
 * 两件事必须钉死:
 *   ① 判据与 manifest.test.js 用的是**同一份实现** —— 保存时不拦, 存进去的机位就会把
 *      那条产物测试弄红, 而那时人早已离开页面, 根本联想不到是自己存的视角;
 *   ② 写回必须是**定点文本替换**。实测: 这份 manifest 在 JS 里 parse 再 stringify 会变
 *      441 行(Python 把浮点 3.0 写成 "3.0", JS 写成 "3"), 再叠加 CRLF→LF, "改一个机位"
 *      的 diff 会变成整个文件。所以这里逐字节断言"除了那一块, 别的一个字节都没动"。
 */
import { strict as assert } from 'node:assert'
import test from 'node:test'
import fs from 'node:fs'
import { fileURLToPath } from 'node:url'

import {
  isCameraOutsideFootprint,
  validateStationCamera,
  hasManualCamera,
} from '../../src/three-d/twin/stationViewRules.js'
import { patchStationCamera } from '../../src/three-d/twin/stationViewWriter.js'

const MANIFEST_PATH = fileURLToPath(
  new URL('../../../three_d/models/device-manifest.json', import.meta.url))
const RAW = fs.readFileSync(MANIFEST_PATH, 'utf8')
const MANIFEST = JSON.parse(RAW)
const BOUNDS = MANIFEST.machine.bounds

// ── 判据 ────────────────────────────────────────────────────────────────────

test('现产物里 13 个工位的机位全部合法(判据与产物测试同源)', () => {
  for (const station of MANIFEST.stations) {
    if (!station.camera?.pos) continue
    assert.ok(isCameraOutsideFootprint(station.camera.pos, BOUNDS),
      `${station.id} 的既有机位过不了判据 —— 判据写错了`)
  }
})

test('落在整机水平轮廓内部的机位被拒(镜头会钻进机柜)', () => {
  const inside = { pos: [...BOUNDS.center], target: [0, 0, 0] }
  assert.equal(isCameraOutsideFootprint(inside.pos, BOUNDS), false)
  const verdict = validateStationCamera(inside, BOUNDS)
  assert.equal(verdict.ok, false)
  assert.match(verdict.reason, /机柜/, '拒绝原因要说清后果, 不能只说"非法"')
})

test('俯视机位(XZ 在中心正上方)同样被拒 —— 判据只看水平面', () => {
  const top = { pos: [BOUNDS.center[0], BOUNDS.center[1] + 5, BOUNDS.center[2]], target: BOUNDS.center }
  assert.equal(validateStationCamera(top, BOUNDS).ok, false)
})

test('机位与目标点重合被拒(相机没有朝向)', () => {
  const same = { pos: [9, 9, 9], target: [9, 9, 9] }
  assert.equal(validateStationCamera(same, BOUNDS).ok, false)
})

test('残缺数据被拒, 不炸', () => {
  assert.equal(validateStationCamera(null, BOUNDS).ok, false)
  assert.equal(validateStationCamera({ pos: [1, 2] , target: [0, 0, 0] }, BOUNDS).ok, false)
  assert.equal(validateStationCamera({ pos: [1, 2, NaN], target: [0, 0, 0] }, BOUNDS).ok, false)
})

test('合法机位放行', () => {
  const station = MANIFEST.stations.find((s) => s.id === 'RACK')
  assert.equal(validateStationCamera(station.camera, BOUNDS).ok, true)
})

test('hasManualCamera: 只认 manual 标记, 管线自动烘的不算', () => {
  assert.equal(hasManualCamera({ camera: { pos: [1, 1, 1], target: [0, 0, 0] } }), false)
  assert.equal(hasManualCamera({ camera: { pos: [1, 1, 1], target: [0, 0, 0], manual: true } }), true)
  assert.equal(hasManualCamera(null), false)
})

// ── 定点写回 ────────────────────────────────────────────────────────────────

const NEW_CAMERA = { pos: [-2.5, 1.25, 0.5], target: [-1.0, 0.4, 0.0], manual: true }

test('写回后仍是合法 JSON, 且目标工位的机位已更新', () => {
  const next = patchStationCamera(RAW, 'RACK', NEW_CAMERA)
  const parsed = JSON.parse(next)
  const rack = parsed.stations.find((s) => s.id === 'RACK')
  assert.deepEqual(rack.camera.pos, NEW_CAMERA.pos)
  assert.deepEqual(rack.camera.target, NEW_CAMERA.target)
  assert.equal(rack.camera.manual, true)
})

test('除目标工位外, 其余 stations 一字未动', () => {
  const next = JSON.parse(patchStationCamera(RAW, 'RACK', NEW_CAMERA))
  for (const station of MANIFEST.stations) {
    if (station.id === 'RACK') continue
    const after = next.stations.find((s) => s.id === station.id)
    assert.deepEqual(after, station, `${station.id} 被误改了`)
  }
})

test('整份文件只有那一个 camera 块变了(diff 不许扩散)', () => {
  const next = patchStationCamera(RAW, 'RACK', NEW_CAMERA)
  const before = RAW.split(/\r?\n/)
  const after = next.split(/\r?\n/)
  // 找出第一处与最后一处差异, 中间必须落在 RACK 的 camera 块里(十几行以内)
  let head = 0
  while (head < before.length && before[head] === after[head]) head += 1
  let tail = 0
  while (tail < before.length - head && before.at(-1 - tail) === after.at(-1 - tail)) tail += 1
  const changedBefore = before.length - head - tail
  const changedAfter = after.length - head - tail
  // 上限按"带 auto 备份的完整 camera 块"给: pos(5)+target(5)+manual(1)+auto(12)+括号 ≈ 26 行。
  // 2026-08-14 用户给全部 10 个工位都存了人工视角, 现产物里的块就是这个体量 ——
  // 原来的 16 行上限是按无 auto 的裸块估的, 会把正常的定点替换误判成重排
  assert.ok(changedBefore <= 26 && changedAfter <= 26,
    `改动跨了 ${changedBefore}→${changedAfter} 行, 说明不是定点替换而是整体重排`)
})

test('保留 CRLF —— 写成 LF 会让 diff 变成整个文件', () => {
  const crlf = '{\r\n  "stations": [\r\n    {\r\n      "id": "A",\r\n'
    + '      "camera": {\r\n        "pos": [\r\n          1.0\r\n        ],\r\n'
    + '        "target": [\r\n          2.0\r\n        ]\r\n      }\r\n    }\r\n  ]\r\n}'
  const next = patchStationCamera(crlf, 'A', { pos: [3, 4, 5], target: [6, 7, 8] })
  assert.ok(next.includes('\r\n'), '原文是 CRLF, 输出也必须是 CRLF')
  assert.equal(next.includes('\n\n'), false)
  assert.deepEqual(JSON.parse(next).stations[0].camera.pos, [3, 4, 5])
})

test('整数值照 Python 风格补小数点(与文件其余部分同款)', () => {
  const next = patchStationCamera(RAW, 'RACK', { pos: [2, 0, -3], target: [1, 1, 1] })
  assert.match(next, /"pos": \[\r?\n\s+2\.0,/, '整数值应写成 2.0 而不是 2')
  assert.deepEqual(JSON.parse(next).stations.find((s) => s.id === 'RACK').camera.pos, [2, 0, -3])
})

test('auto 嵌套块能正确排版并读回', () => {
  const withAuto = {
    ...NEW_CAMERA,
    auto: { pos: [-2.09, 0.754, 0.013], target: [-1.18, 0.372, 0.004] },
  }
  const rack = JSON.parse(patchStationCamera(RAW, 'RACK', withAuto))
    .stations.find((s) => s.id === 'RACK')
  assert.deepEqual(rack.camera.auto.pos, [-2.09, 0.754, 0.013])
  assert.deepEqual(rack.camera.auto.target, [-1.18, 0.372, 0.004])
  assert.equal(rack.camera.manual, true)
})

test('清除(不带 manual)后 flyToStation 会回到自动取景', () => {
  const rack = JSON.parse(patchStationCamera(RAW, 'RACK', { pos: [1.5, 1, 1.5], target: [0, 0, 0] }))
    .stations.find((s) => s.id === 'RACK')
  assert.equal(rack.camera.manual, undefined)
  assert.equal(hasManualCamera(rack), false)
})

test('每个工位都能被定点改到(不串台到 axes/actuators 里的同名 id)', () => {
  for (const station of MANIFEST.stations) {
    const next = JSON.parse(patchStationCamera(RAW, station.id, NEW_CAMERA))
    assert.deepEqual(next.stations.find((s) => s.id === station.id).camera.pos, NEW_CAMERA.pos)
    // 顺带确认 axes 段没被碰过 —— 那里也有 "id" 键
    assert.deepEqual(next.axes, MANIFEST.axes, `改 ${station.id} 时误伤了 axes 段`)
  }
})

test('工位不存在时明确抛错, 不静默写坏文件', () => {
  assert.throws(() => patchStationCamera(RAW, '不存在的工位', NEW_CAMERA), /找不到工位/)
})
