/**
 * 功能: 程序化影棚环境贴图 —— 数块 HDR 发光灯板经 PMREM 生成 scene.environment.
 *
 * 为什么不用 three 自带的 RoomEnvironment: 它是个低对比的小灰房间, 金属反射不出
 * 任何"高光形状", 只能得到一团均匀灰 —— 正是"金属像灰泥"的直接来源. 产品渲染图里
 * 金属的质感全靠反射里的长条柔光箱形状(台面拉丝铝上那道长高光、圆柱件上的环形眉),
 * 这里就按摄影棚的布灯思路摆几块发光板, 专门制造这些形状.
 *
 * 为什么不用外部 HDR 文件: 离线环境要能跑, 仓库也不想背一张几 MB 的 .hdr;
 * 程序化灯板生成一次只要几毫秒, 效果对这种"中性影棚"场景足够.
 *
 * 实现要点:
 *   - 灯板是 MeshBasicMaterial, 强度直接乘进 color(分量可以 > 1);
 *     PMREM 的目标是半浮点缓冲, HDR 亮度会被完整保留, 这正是高光形状的来源.
 *   - fromScene 的模糊 sigma 取小值(0.04): 模糊大了灯板边缘糊掉, 长条高光就没了;
 *     粗糙表面的模糊交给 PMREM 的 mip 链, 不需要在源头糊.
 *   - 相机在原点, 所有灯板朝向原点附近摆放, 距离/尺寸按"米"理解即可.
 */
import * as THREE from 'three'

/**
 * 灯板布局: 微暖主光 + 微冷侧光平均下来是中性白平衡, 白色机身不会被染色.
 * intensity 是 HDR 倍率; 想整体提亮反射请调 scene.environmentIntensity, 别动这里.
 */
const PANELS = [
  // 顶部大洗光: 直径盖过整机的柔光顶, 决定一切朝上表面(台面!)的基础亮度.
  // 校准记录(2026-08-01): 无洗光时台面近黑(粗糙金属的明度=环境平均亮度),
  // ×1.6 时整机泛白阴影全无 —— ×0.9 落在"台面中灰、白件仍是白"的窗口里.
  { size: [14, 14], position: [0, 7.8, 0], color: 0xffffff, intensity: 0.9 },
  // 主柔光箱: 左上大面积, 白钣金的明暗渐变与主高光来源
  { size: [6, 2.4], position: [-4, 5.5, 3], color: 0xfff2e4, intensity: 5.0 },
  // 顶部长条: 正上方细长亮灯管, 台面拉丝铝上的长条高光形状(比洗光亮一个数量级)
  { size: [8, 1.0], position: [0, 7.5, 0], color: 0xffffff, intensity: 3.5 },
  // 侧补板: 右后方微冷, 金属边缘亮线与背侧反射
  { size: [4, 1.6], position: [5, 3, -3], color: 0xe8f0f8, intensity: 2.2 },
  // 环形板: 低位环灯, 圆柱类零件(气缸/导柱)上的环形眉高光
  { ring: [0.7, 1.1], position: [-3.5, 1.2, -4.5], color: 0xffffff, intensity: 1.5 },
]

/** 包住全场的底噪盒: 金属暗部的反射底色. 校准记录: 0x202226×0.35 黑块 /
 *  0x9aa0a6×0.85 泛白, 中暗灰是"黑件有层次、白件不灰"的平衡点 */
const SHELL = { size: [24, 14, 24], color: 0x565b61, intensity: 0.9 }

/**
 * 功能: 生成影棚环境贴图. 内部场景用后即弃, 只返回 PMREM 纹理.
 * @param {THREE.WebGLRenderer} renderer 渲染器(PMREM 需要)
 * @returns {THREE.Texture} 可直接赋给 scene.environment 的环境贴图
 */
export function createStudioEnvTexture(renderer) {
  const scene = new THREE.Scene()
  const disposables = []

  /**
   * 功能: 添一块发光板并登记待释放资源.
   * @param {THREE.BufferGeometry} geometry 灯板几何
   * @param {number} color 基色
   * @param {number} intensity HDR 倍率
   * @param {[number, number, number]} position 位置
   * @param {THREE.Vector3|null} lookAt 朝向点(null 表示自定朝向)
   * @returns {THREE.Mesh} 灯板网格
   */
  function addPanel(geometry, color, intensity, position, lookAt) {
    const material = new THREE.MeshBasicMaterial({ side: THREE.DoubleSide })
    material.color.set(color).multiplyScalar(intensity)
    const mesh = new THREE.Mesh(geometry, material)
    mesh.position.set(...position)
    if (lookAt) mesh.lookAt(lookAt)
    scene.add(mesh)
    disposables.push(geometry, material)
    return mesh
  }

  const center = new THREE.Vector3(0, 1, 0) // 设备大致体量的中心高度
  for (const panel of PANELS) {
    const geometry = panel.ring
      ? new THREE.RingGeometry(panel.ring[0], panel.ring[1], 48)
      : new THREE.PlaneGeometry(panel.size[0], panel.size[1])
    addPanel(geometry, panel.color, panel.intensity, panel.position, center)
  }

  // 底噪盒: BackSide 反转包住相机
  const shellGeometry = new THREE.BoxGeometry(...SHELL.size)
  const shellMaterial = new THREE.MeshBasicMaterial({ side: THREE.BackSide })
  shellMaterial.color.set(SHELL.color).multiplyScalar(SHELL.intensity)
  scene.add(new THREE.Mesh(shellGeometry, shellMaterial))
  disposables.push(shellGeometry, shellMaterial)

  const pmrem = new THREE.PMREMGenerator(renderer)
  const envTexture = pmrem.fromScene(scene, 0.04).texture

  for (const resource of disposables) resource.dispose()
  pmrem.dispose()

  return envTexture
}
