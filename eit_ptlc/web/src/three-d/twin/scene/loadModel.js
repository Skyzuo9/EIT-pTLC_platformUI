/**
 * 功能: GLB 模型加载与节点索引构建.
 *
 * 职责:
 *   1. 加载 machine.glb(整机)与可选的 cr5.glb(机械臂), 支持 meshopt 压缩;
 *   2. 建立"节点路径 -> Object3D"索引, 这是 device-manifest 里 glbNode 字段的解析依据;
 *   3. 单位归一: CAD 导出的 GLB 通常以毫米为单位, 统一缩放到米, 否则相机裁剪面难以设定;
 *   4. 统计网格/三角形/材质数量, 供性能预算核对.
 */
import * as THREE from 'three'
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js'
import { MeshoptDecoder } from 'three/examples/jsm/libs/meshopt_decoder.module.js'

/**
 * 功能: 创建配置好解压器的 GLTFLoader.
 * @returns {GLTFLoader} 加载器实例
 */
function createLoader() {
  const loader = new GLTFLoader()
  // 管线第 04 步用 gltf-transform 做 meshopt 压缩, 这里必须装上对应解码器
  loader.setMeshoptDecoder(MeshoptDecoder)
  return loader
}

/**
 * 功能: 递归遍历场景图, 建立以"/"分隔的层级路径索引 —— **three 名与 glTF 原名双写**.
 *
 * 例: 节点 ST_SAMPLING 下的 AXIS_4X 下的 CARRIAGE, 索引键为 "ST_SAMPLING/AXIS_4X/CARRIAGE".
 * 同时把不含路径的裸名也登记进去(重名时保留第一个), 方便手写 manifest 时偷懒只写末段名.
 *
 * 为什么要按原名再建一套平行索引: three 的 GLTFLoader 会用 PropertyBinding.sanitizeNodeName
 * 消毒节点名 —— 空格换下划线、**点号等特殊字符直接剥掉**. Blender 里重名对象(如多条轴
 * 的滑车组都叫 CARRIAGE)带 .001/.002 后缀, manifest(由 structure.json 生成)记录的是
 * 带点原名, 只按 three 名建索引会解析失败(实测 axis_3y/axis_5z 因 CARRIAGE.001→
 * CARRIAGE001 变成死轴). 原名取自 userData.origName(loadMachine 在建索引前已写好);
 * 已验证全模型 1041 节点双写零键冲突 —— 被消毒的原名必含 three 名不可能含有的字符,
 * 未被消毒的与 three 名逐字相同指向同一对象.
 *
 * @param {THREE.Object3D} root 根节点(其自身名字不计入路径)
 * @returns {Map<string, THREE.Object3D>} 路径到对象的映射
 */
export function buildNodeIndex(root) {
  /** @type {Map<string, THREE.Object3D>} */
  const index = new Map()

  /**
   * @param {THREE.Object3D} object 当前节点
   * @param {string} prefix 父级路径前缀(three 名)
   * @param {string} origPrefix 父级路径前缀(glTF 原名)
   */
  function walk(object, prefix, origPrefix) {
    for (const child of object.children) {
      const name = child.name || `_unnamed_${child.id}`
      const orig = child.userData?.origName || name
      const path = prefix ? `${prefix}/${name}` : name
      const origPath = origPrefix ? `${origPrefix}/${orig}` : orig

      // three 名分支保持原语义: 全路径无守卫(后写覆盖), 裸名首个命中优先
      index.set(path, child)
      if (!index.has(name)) index.set(name, child)
      // 原名平行分支: 全部带守卫, 不与 three 名分支争键
      if (origPath !== path && !index.has(origPath)) index.set(origPath, child)
      if (orig !== name && !index.has(orig)) index.set(orig, child)

      walk(child, path, origPath)
    }
  }

  walk(root, '', '')
  return index
}

/**
 * 功能: 统计一棵场景图的渲染开销指标.
 * @param {THREE.Object3D} root 根节点
 * @returns {{meshes: number, drawCalls: number, triangles: number, materials: number, nodes: number}}
 *          网格数/绘制调用数/三角形数/材质数/节点总数
 */
export function collectStats(root) {
  let meshes = 0
  let drawCalls = 0
  let triangles = 0
  let nodes = 0
  const materials = new Set()

  root.traverse((object) => {
    nodes += 1
    if (!object.isMesh) return
    meshes += 1

    const geometry = object.geometry
    const groups = geometry?.groups?.length || 0
    // 一个几何体若有多个材质组, 每组是一次独立的绘制调用
    drawCalls += Math.max(groups, 1)

    if (geometry) {
      const count = geometry.index ? geometry.index.count : geometry.attributes.position?.count || 0
      triangles += Math.floor(count / 3)
    }

    const material = object.material
    if (Array.isArray(material)) material.forEach((m) => materials.add(m.uuid))
    else if (material) materials.add(material.uuid)
  })

  return { meshes, drawCalls, triangles, materials: materials.size, nodes }
}

/**
 * 功能: 计算对象的精确世界包围盒.
 *
 * 必须用 Box3 的 precise 模式(逐顶点), 不能用默认的快速模式. 默认模式取每个几何体
 * 已缓存的局部 AABB 再按世界矩阵变换八个角点重新拟合; 而管线第 04 步的
 * KHR_mesh_quantization 压缩会把每个图元的局部包围盒变成一个立方体(量化体积),
 * 该立方体经旋转后重新拟合会显著膨胀 —— 实测能把 2.6×1.5×2.1 m 的整机报成
 * 4.0×3.6×4.0 m, 进而让自动取景把相机拉得过远.
 * 逐顶点计算在加载时只做一次, 开销可以接受.
 *
 * @param {THREE.Object3D} object 目标对象
 * @returns {THREE.Box3} 世界坐标包围盒
 */
export function computeBounds(object) {
  object.updateMatrixWorld(true)
  return new THREE.Box3().setFromObject(object, true)
}

/**
 * 功能: 推断模型的单位缩放系数.
 *
 * CAD 中性格式(STEP)一律以毫米建模, 转出的 GLB 因此可能是"1 单位 = 1 毫米";
 * 而三维场景里用米做单位才便于设定相机裁剪面、雾和灯光衰减. 这里按整机尺寸判断:
 * 一台实验室设备的合理尺寸是几米, 若包围盒对角线大于 100, 基本可断定单位是毫米.
 *
 * @param {THREE.Object3D} object 模型根节点
 * @returns {{scale: number, diagonal: number, unit: string}} 缩放系数/对角线长度/判定单位
 */
export function inferUnitScale(object) {
  // 量级判断而已, 这里用快速模式即可
  const diagonal = new THREE.Box3().setFromObject(object).getSize(new THREE.Vector3()).length()
  if (diagonal > 100) return { scale: 0.001, diagonal, unit: 'mm' }
  return { scale: 1, diagonal, unit: 'm' }
}

/**
 * 功能: 加载一个 GLB 文件.
 * @param {string} url 模型地址
 * @param {(fraction: number, loaded: number, total: number) => void} [onProgress] 进度回调(0~1)
 * @returns {Promise<import('three/examples/jsm/loaders/GLTFLoader.js').GLTF>} glTF 解析结果
 */
export function loadGLB(url, onProgress) {
  const loader = createLoader()
  return new Promise((resolve, reject) => {
    loader.load(
      url,
      resolve,
      (event) => {
        if (!onProgress) return
        // 服务端未提供 Content-Length 时 total 为 0, 此时无法算百分比
        const fraction = event.total > 0 ? event.loaded / event.total : 0
        onProgress(fraction, event.loaded, event.total)
      },
      (error) => reject(new Error(`模型加载失败: ${url} (${error?.message || error})`)),
    )
  })
}

/**
 * 功能: 加载整机模型并完成单位归一、居中与索引构建.
 *
 * @param {object} options 参数对象
 * @param {string} options.url 整机 GLB 地址
 * @param {(fraction: number) => void} [options.onProgress] 加载进度回调
 * @param {boolean} [options.center=true] 是否把模型水平居中并把底面贴到 y=0
 * @param {number} [options.unitScale] 手动指定缩放系数; 不传则自动推断
 * @returns {Promise<{root: THREE.Group, gltf: object, nodeIndex: Map<string, THREE.Object3D>,
 *                    stats: object, unit: object, loadMs: number}>} 加载结果
 */
export async function loadMachine({ url, onProgress, center = true, unitScale }) {
  const started = performance.now()
  const gltf = await loadGLB(url, onProgress)

  // 外层再包一个 Group: 缩放/居中都作用在这一层, 内部节点保持导出时的原始变换,
  // 这样 manifest 里手写的 glbNode 路径与 Blender 中看到的层级完全一致.
  const root = new THREE.Group()
  root.name = 'MACHINE_ROOT'
  root.add(gltf.scene)

  // 把 glTF **原名**存进 userData: three 加载时会消毒节点名(空格→下划线等),
  // 而 Blender/管线侧用的是原名 —— 工作台的显式删除名单必须写原名才能命中
  // (硬约束 27; 曾因此出现"标了删除、重跑后还在"的静默失败).
  try {
    const nodesJson = gltf.parser?.json?.nodes || []
    gltf.parser?.associations?.forEach?.((value, object) => {
      const index = value?.nodes
      if (index === undefined || !object?.isObject3D) return
      const orig = nodesJson[index]?.name
      if (orig && orig !== object.name) object.userData.origName = orig
    })
  } catch {
    /* 原名仅用于保存名单, 拿不到不影响显示 */
  }

  const unit = unitScale ? { scale: unitScale, unit: 'manual' } : inferUnitScale(gltf.scene)
  gltf.scene.scale.setScalar(unit.scale)

  if (center) {
    // 缩放后重新求包围盒, 把模型水平居中、底面落到 y=0, 便于地面与网格对齐
    const box = computeBounds(gltf.scene)
    const centerPoint = box.getCenter(new THREE.Vector3())
    gltf.scene.position.x -= centerPoint.x
    gltf.scene.position.z -= centerPoint.z
    gltf.scene.position.y -= box.min.y
  }

  root.updateMatrixWorld(true)

  return {
    root,
    gltf,
    nodeIndex: buildNodeIndex(gltf.scene),
    stats: collectStats(gltf.scene),
    unit,
    loadMs: Math.round(performance.now() - started),
  }
}

/**
 * 功能: 彻底释放一棵场景图占用的 GPU 资源(几何体/材质/贴图).
 *
 * three.js 不会自动回收 GPU 侧资源; 在常驻页面里反复加载模型而不释放, 显存会持续增长
 * 直到丢失 WebGL 上下文, 因此这是 SceneManager.dispose 契约中最关键的一环.
 *
 * @param {THREE.Object3D} root 根节点
 * @returns {void}
 */
export function disposeObject(root) {
  root.traverse((object) => {
    if (!object.isMesh) return
    object.geometry?.dispose()
    const materials = Array.isArray(object.material) ? object.material : [object.material]
    for (const material of materials) {
      if (!material) continue
      for (const value of Object.values(material)) {
        if (value && value.isTexture) value.dispose()
      }
      material.dispose()
    }
  })
  root.clear()
}
