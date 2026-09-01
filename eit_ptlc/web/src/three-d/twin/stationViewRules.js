/**
 * 功能: 工位机位(stations[].camera)的合法性判据 —— 保存前校验与产物看门狗**共用这一份**.
 *
 * 为什么要抽出来: manifest 里的机位原本只由三维管线生成, 由 tests/three-d/manifest.test.js
 * 守着"不许落在整机水平轮廓内部"(否则镜头钻进机柜只看到钣金内壁)。现在「显示 → 模块视角
 * 设定」让操作员也能写这个字段, 若保存时不按同一条判据拦一下, 存一个机柜内部的机位就会
 * 把那条产物测试弄红 —— 而那时人已经离开这个页面了, 根本联想不到是自己刚才存的视角。
 *
 * 一份判据两处用: 这里是实现, 测试 import 它。不是两份各写一遍。
 */

/**
 * 功能: 判断一个机位是否落在整机水平轮廓之外(合法).
 *
 * 只看水平面: 俯视机位在 XZ 上可能正对中心但 Y 很高, 那是合法的取景;
 * 判据与三维管线 camera_preset 的产出口径一致。
 * @param {number[]|null|undefined} pos 机位世界坐标 [x, y, z](米)
 * @param {object|null} bounds 整机包围盒 {center: number[], size: number[]}
 * @returns {boolean} 是否在轮廓之外
 */
export function isCameraOutsideFootprint(pos, bounds) {
  if (!Array.isArray(pos) || pos.length !== 3) return false
  if (!bounds || !Array.isArray(bounds.center) || !Array.isArray(bounds.size)) return true
  const halfX = bounds.size[0] / 2
  const halfZ = bounds.size[2] / 2
  const dx = Math.abs(pos[0] - bounds.center[0])
  const dz = Math.abs(pos[2] - bounds.center[2])
  return dx > halfX || dz > halfZ
}

/**
 * 功能: 校验一份待保存的机位, 不合法时给出**能照着改**的中文原因.
 * @param {object|null} camera 机位 {pos: number[], target: number[]}
 * @param {object|null} bounds 整机包围盒
 * @returns {{ok: boolean, reason: string}} 校验结果
 */
export function validateStationCamera(camera, bounds) {
  const pos = camera?.pos
  const target = camera?.target
  const triple = (v) => Array.isArray(v) && v.length === 3 && v.every((n) => Number.isFinite(n))
  if (!triple(pos) || !triple(target)) {
    return { ok: false, reason: '机位数据不完整(pos / target 必须各是三个有限数)' }
  }
  if (pos[0] === target[0] && pos[1] === target[1] && pos[2] === target[2]) {
    return { ok: false, reason: '机位与目标点重合, 相机没有朝向' }
  }
  if (!isCameraOutsideFootprint(pos, bounds)) {
    return {
      ok: false,
      reason: '当前机位落在整机水平轮廓内部 —— 存下来后跳转会把镜头送进机柜里, '
        + '只看得到钣金内壁。请把相机拉到机器外面再保存。',
    }
  }
  return { ok: true, reason: '' }
}

/**
 * 功能: 判断一个工位的机位是不是人工设过的(而不是管线自动烘的).
 * @param {object|null} station 工位定义
 * @returns {boolean} 是否人工设定
 */
export function hasManualCamera(station) {
  return Boolean(station?.camera?.manual)
}
