/**
 * 功能: 共享幽灵材质单例 —— isolation(聚焦隔离)与 intro(开场扫场)共用同一个
 * MeshStandardMaterial 实例.
 *
 * 为什么必须共享一个实例:
 *   1. 幽灵浓度滑杆(focus.ghostOpacity)要"改一处全场变", 两个消费方各建一份就会漂移;
 *   2. isGhostMaterial() 的引用相等判断是 intro x isolation 互斥的 L2 机械兜底 ——
 *      两本台账谁都不许把幽灵材质记成"原材质"(否则退出时永久写回, 整机回不到实体);
 *   3. 少一次 draw-call 材质切换.
 *
 * 生命周期: 模块级单例(沙盒每页一实例), 两个特效的 dispose 都**不**销毁它;
 * disposeGhostMaterial 只留给整页 teardown.
 */
import * as THREE from 'three'

/** @type {THREE.MeshStandardMaterial|null} */
let _mat = null

/**
 * 功能: 取共享幽灵材质(惰性创建; 首调按主题取色).
 * @param {object} ctx 沙盒上下文(读 theme 与 config.focus.ghostOpacity)
 * @returns {THREE.MeshStandardMaterial}
 */
export function ghostMaterial(ctx) {
  if (!_mat) {
    _mat = new THREE.MeshStandardMaterial({
      color: ctx.theme === 'light' ? 0x9aa8b8 : 0x6b7a8c,
      roughness: 0.9,
      metalness: 0,
      transparent: true,
      opacity: ctx.config.focus.ghostOpacity,
      depthWrite: false, // 半透明零件互相遮挡会出脏层叠(正式页 ViewTools 同款结论)
    })
  }
  return _mat
}

/**
 * 功能: 引用相等判断 —— 该材质是不是共享幽灵材质.
 * @param {object} material 待判材质(数组材质请自行逐项判)
 * @returns {boolean}
 */
export function isGhostMaterial(material) {
  return _mat !== null && material === _mat
}

/**
 * 功能: 幂等同步幽灵浓度(isolation.update 与 intro.update 各自每帧调, 谁在场谁生效).
 * @param {number} value 目标不透明度
 * @returns {void}
 */
export function syncGhostOpacity(value) {
  if (_mat && _mat.opacity !== value) _mat.opacity = value
}

/** 功能: 释放材质(仅整页 teardown 用; 特效级 dispose 不要调). */
export function disposeGhostMaterial() {
  _mat?.dispose()
  _mat = null
}
