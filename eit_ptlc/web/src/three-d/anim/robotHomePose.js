/**
 * 功能: 把机械臂摆到折叠工作姿态(robot-main.home) —— 装配/材质工作台共用.
 *
 * 这两个视图不跑动作片段, GLB 里烘焙的是竖直零位; 为了与 Studio/演示里的观感一致,
 * 加载完成后把六轴摆到标定 home. 数据源是管线产物(device-manifest 的关节 spec +
 * robot-points 的标定六轴), 不硬编码任何角度: 重标定后两份文件重新生成, 这里自动跟随.
 */
import { RobotJointDriver } from './RobotJointDriver.js'

export const HOME_POINT_ID = 'robot-main.home'

async function fetchJson(url) {
  const response = await fetch(url)
  if (!response.ok) throw new Error(`HTTP ${response.status} (${url})`)
  return response.json()
}

/**
 * 功能: 按标定点位把机械臂摆成折叠姿态. 任何失败都静默降级(保持 GLB 零位).
 * @param {import('../twin/scene/SceneManager.js').SceneManager} manager 已完成 loadMachineModel
 * @param {object} [options]
 * @param {string} [options.manifestUrl] 关节 spec 来源
 * @param {string} [options.pointsUrl] 标定点位目录来源
 * @param {string} [options.pointId] 目标点位 id
 * @returns {Promise<{applied: boolean, missing: string[]}>} applied=false 表示已降级
 */
export async function applyRobotHomePose(manager, options = {}) {
  const {
    manifestUrl = '/api/3d/assets/models/device-manifest.json',
    pointsUrl = '/api/3d/assets/generated/robot-points.json',
    pointId = HOME_POINT_ID,
  } = options
  try {
    const [manifest, catalog] = await Promise.all([fetchJson(manifestUrl), fetchJson(pointsUrl)])
    if (catalog?.schema !== 'ptlc.robot-points/v1') throw new Error('点位目录 schema 不符')
    const joints = catalog?.points?.[pointId]?.joint
    if (!Array.isArray(joints) || joints.length !== 6) throw new Error(`点位 ${pointId} 缺 joint 六元组`)
    if (!manifest?.robot?.joints?.length) throw new Error('manifest 缺 robot.joints')

    // 全路径优先、裸叶名回退(与 MachineRig 同款): raw.glb 里 manifest 的挂载全路径
    // 不存在, 但 CR5_J*_ROTOR 裸名在三个 GLB 的节点索引里都有登记
    const resolve = (path) => {
      if (!path) return undefined
      const direct = manager.getNode(path)
      if (direct) return direct
      const leaf = String(path).split('/').pop()
      return leaf ? manager.getNode(leaf) : undefined
    }
    const driver = new RobotJointDriver(manifest.robot, resolve)
    if (driver.missing.length) console.warn('[robot] 部分关节未解析:', driver.missing)
    if (!driver.joints.length) throw new Error('六个关节全部未命中')

    // 已烘焙检测: ROTOR 按设计是单位旋转节点(挂载变换在 ORIGIN 上). 管线的
    // raw 链会把 home 姿态直接烘进 ROTOR(blender_clean 的 bake_joints_deg),
    // 那种 GLB 加载出来 ROTOR 就带非单位四元数 —— 再叠加一次会关节角翻倍.
    // 阈值 1°: 未烘焙=恒等, 烘焙零位也只有 zeroOffsetDeg 的 0.2° 量级.
    const baked = driver.joints.some((joint) => {
      const w = Math.min(1, Math.abs(joint.baseQuat.w))
      return (2 * Math.acos(w) * 180) / Math.PI > 1
    })
    if (baked) {
      console.info('[robot] GLB 已烘焙姿态, 跳过前端摆姿')
      return { applied: false, missing: driver.missing }
    }

    driver.setJointsDeg(joints, { continuous: false })
    manager.invalidateShadows()
    return { applied: true, missing: driver.missing }
  } catch (err) {
    console.warn('[robot] 初始折叠姿态未应用(保持模型零位):', err?.message || err)
    return { applied: false, missing: [] }
  }
}
