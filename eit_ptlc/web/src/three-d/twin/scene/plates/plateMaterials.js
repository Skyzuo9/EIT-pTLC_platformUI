/**
 * 功能: 薄层板两层的材质 —— 半透明玻璃基板 + 不透明哑光白硅胶面.
 *
 * 两条硬约定(都踩过坑, 见 three_d/docs/CLAUDE.md):
 *   第 12 条 —— 玻璃材质必须从锚点材质 **clone()** 派生再改。`MAT_GLASS_FFFFFF` 被
 *   8 个缸盖石英玻璃 + 下相机盖板共用, 直接改共享对象会让整机一起变样。
 *   任何**按物体/世界空间投影**的程序化纹理都不能直接套在板上: 板用的是语义非均匀
 *   scale([0.2, 0.001, 0.2]), 按"反量化 scale"折算的坐标在这里会被放大成鳄鱼皮。
 *   要给板加纹理就得单独走一套按板自身尺寸标定的坐标, 不能沿用整机那套。
 */
import * as THREE from 'three'

/**
 * 硅胶面基色。**不是纯白**: `#ffffff` 在 Neutral 色调映射下会顶到削波, 读起来像一片
 * 自发光塑料, 而且会蹭到 SelectiveBloom 的亮度阈值。冷调米白既保住"不透明白色涂层"
 * 的语义, 又留出高光余量。
 */
export const SILICA_COLOR = 0xf1f3f5

/** 玻璃断面的青绿色衰减 —— "这是真玻璃"最关键的一笔, 少了它就是一块灰亚克力。 */
export const GLASS_ATTENUATION_COLOR = 0xdde8ec

/**
 * 功能: 造硅胶层材质(不透明哑光白).
 *
 * roughness 0.92 = 粉末床近朗伯; envMapIntensity 压到 0.22 是因为影棚环境贴图默认
 * 强度会在这么平的一块面上糊出整片反射, 观感直接变成亚克力板。
 * alphaTest 而非 transparent: 刮取穿透(阶段 5)走 discard, 保住深度写入与排序无关性。
 *
 * @returns {THREE.MeshStandardMaterial}
 */
export function createSilicaMaterial() {
  return new THREE.MeshStandardMaterial({
    name: 'MAT_TLC_SILICA',
    color: SILICA_COLOR,
    roughness: 0.92,
    metalness: 0.0,
    envMapIntensity: 0.22,
    alphaTest: 0.5,
    side: THREE.FrontSide,
  })
}

/**
 * 功能: 造玻璃基板材质(半透明), 优先从 CAD 锚点材质克隆派生.
 *
 * transmission 取 0.86 而不是锚点原本的 0.92: 板的上表面压着一层不透明硅胶, 透射再高
 * 会让这 2mm 玻璃在深色背景里"消失", 侧视看不出分层。
 *
 * @param {THREE.Material|null} source 锚点上的原材质(通常是 MAT_GLASS_FFFFFF)
 * @returns {THREE.Material}
 */
export function createGlassMaterial(source = null) {
  const base = Array.isArray(source) ? source[0] : source
  const material = base?.clone?.() || new THREE.MeshPhysicalMaterial()
  material.name = 'MAT_TLC_PLATE_GLASS'
  material.color = new THREE.Color(0xffffff)
  material.transmission = 0.86
  material.ior = 1.46
  material.thickness = 0.002
  material.attenuationColor = new THREE.Color(GLASS_ATTENUATION_COLOR)
  material.attenuationDistance = 0.05
  material.roughness = 0.06
  material.metalness = 0.0
  material.transparent = true
  material.depthWrite = true
  material.side = THREE.FrontSide
  material.needsUpdate = true
  return material
}

/**
 * 功能: 关掉板玻璃的透射, 退化为普通混合透明.
 *
 * 为什么要留这个开关: three 只要场景里存在 transmission>0 的材质, 就会把场景**再渲一遍**
 * 进 backbuffer, 于是每个板网格被提交两次。该 pass 今天就已经因为缸盖石英玻璃在跑了,
 * 但板会把它的规模按网格数放大。关掉后板从透射 pass 里消失, 观感损失极小 ——
 * 板背面本就贴着缸底/托盘/料仓, 根本看不到透射内容。
 *
 * @param {THREE.Material} material createGlassMaterial 的产物
 * @param {boolean} enabled 是否启用透射
 * @returns {void}
 */
export function setGlassTransmission(material, enabled) {
  if (!material) return
  const on = enabled !== false
  material.transmission = on ? 0.86 : 0.0
  material.opacity = on ? 1.0 : 0.45
  material.transparent = true
  material.needsUpdate = true
}
