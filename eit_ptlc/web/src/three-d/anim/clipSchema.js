/**
 * 功能: 动画片段(clip)契约 `ptlc.clip/v1|v2|v3` 的解析、编译与求值 —— 全部纯函数.
 *
 * 设计要点:
 *   1. 步骤(steps)是**编排语法**, 编译成两样东西: 按通道归并的**关键帧表**(连续量:
 *      轴 mm / 关节角)与**离散事件表**(换工具 attach、镜头、强调). 播放器只消费编译产物.
 *   2. `evaluate(compiled, t)` 是纯函数 —— 同一 t 永远得到同一状态, seek 不漂移.
 *      这继承了轴驱动"绝对写"的纪律(见 TwinBindings 的 basePosition+offset).
 *   3. 原语对齐上位机的运动原语: 轴移动(axis) / 机械臂到点(joints) / 通用平移(node,
 *      给气缸留的) / 末端执行器(tool: lock|release, 即快换 DO1) / 镜头 / 等待.
 *   5. `liquid` 是**流体**原语(展缸溶液槽的液面): 值是毫升, 按 id 寻址 manifest 里声明的
 *      液体几何. 注/排液在真机上是泵与阀的事, 但看得见的表现就是缸里的液面涨落 —— 那
 *      正是这条原语要演的. 换算与写入见 MachineStateDriver.setLiquidMl.
 *   4. `plate` 是**工件**原语(薄层色谱板): 片段是标称轨迹演示, 没有物料账本可投影,
 *      所以板的行踪由编排显式写出 —— `{at: 落点}` 摆位、`{carry: true}` 交给吸盘、
 *      `{hide: true}` 收走。落到 PlateStage 上执行, 语义详见那里的头注释。
 *   6. `scrape` 是**板面刮取**原语(拍照刮板工位): loosen(刮松)/clear(收粉露玻璃)两条
 *      0..1 连续通道, 条带矩形在 compiled.scrapeRegions 里由编译器给出. 执行入口
 *      PlateStage.setScrape, 视觉实现见 PlateFaceLayer.applyScrape.
 *   7. `pump`/`pump_valve` 是**注射泵**原语: pump 的值是针筒内**毫升**(单自由度 ——
 *      柱塞位置≡液柱高度≡丝杠转角, 一条通道三个节点全驱动, 见
 *      MachineStateDriver.setPumpMl); pump_valve 的值是 1 起数的**端口号**, 端口→
 *      指针角度按 manifest 的 valvePortAngles 留到写入层换算(角度是 03 构建产物,
 *      烘进片段就是陈旧隐患, 与 liquid 不烘实测截面积同一条纪律).
 *   8. `spot`/`wet` 是另两种**板面痕迹**原语(与 scrape 同族): spot 是点样色带的渐现
 *      进度(0..1, band 号 1 起数, 多条带各自成通道), wet 是溶剂润湿前沿的上行进度
 *      (0..1, 相对 wetRegions 声明的前沿目标高度). 条带/润湿区的板 cm 帧几何在
 *      compiled.spotRegions / wetRegions 里由编译器给出, 执行入口 PlateStage.setSpot /
 *      setWet, 视觉实现 PlateFaceLayer 的痕迹遮罩(与刮取共用一张画布分层合成).
 *
 * 片段 YAML 形如:
 *   schema: ptlc.clip/v1
 *   name: robot.tool_pickup
 *   label: 更换夹爪
 *   home: { axis_mm: { axis_11y: 0 }, joints_deg: [0,0,0,0,0,0] }
 *   steps:
 *     - { label: 地轨就位, dur: 3, ease: inout, do: { axis: { id: axis_11y, to_mm: 450 } } }
 *     - { at: 0, dur: 2, do: { camera: { station: TOOLING } } }   # at 缺省=上一步结束
 *     - { label: 下探, dur: 2, do: { joints: { to_deg: [0,-40,60,null,30,0] } } }  # null=保持
 *     - { label: 气动锁, dur: 1, do: { tool: { action: lock, id: TOOL_PLATE96 } } }
 */
import { parse } from 'yaml'

import { validatePlateStep } from '../twin/bindings/PlateSlots.js'

/**
 * 缓动函数: 伺服轴观感默认 inout。
 *
 * `step` 是**阶跃**: 恒返回 1, 于是 `prev + (next-prev)*eased` 在区间起点就等于 next。
 * 给开关量通道用(主轴自转 on/off) —— 那种通道插值出来的中间值没有物理对应物,
 * 线性过渡等于让刀"半转着"。
 */
export const EASES = {
  linear: (x) => x,
  inout: (x) => (x < 0.5 ? 4 * x * x * x : 1 - (-2 * x + 2) ** 3 / 2),
  out: (x) => 1 - (1 - x) ** 3,
  step: () => 1,
}

/**
 * 功能: 解析 clip YAML 文本并做结构校验.
 * @param {string} text YAML 原文
 * @returns {object} 文档对象
 * @throws {Error} schema 不符或步骤非法
 */
export function parseClip(text) {
  const doc = parse(text)
  if (!doc || !['ptlc.clip/v1', 'ptlc.clip/v2', 'ptlc.clip/v3'].includes(doc.schema)) {
    throw new Error(`clip schema 不是 ptlc.clip/v1、ptlc.clip/v2 或 ptlc.clip/v3: ${doc?.schema}`)
  }
  if (!Array.isArray(doc.steps) || doc.steps.length === 0) {
    throw new Error('clip 没有 steps')
  }
  return doc
}

/** 每步允许的原语键(do 里必须恰好有一个) */
const PRIMITIVES = [
  'axis', 'joints', 'robot_point', 'node', 'actuator', 'linkage',
  'attach', 'detach', 'state', 'tool', 'camera', 'highlight', 'plate', 'light', 'liquid', 'wait',
  'scrape', 'pump', 'pump_valve', 'spindle', 'spot', 'wet', 'powder',
]

/**
 * 功能: 取一步的原语类型.
 * @param {object} step 步骤
 * @returns {string} 原语名
 * @throws {Error} do 缺失或含未知/多个原语
 */
function primitiveOf(step) {
  const body = step.do || {}
  const keys = Object.keys(body).filter((key) => PRIMITIVES.includes(key))
  if (keys.length !== 1) {
    throw new Error(`步骤「${step.label || '?'}」的 do 必须恰好含一个原语, 实际: ${Object.keys(body)}`)
  }
  return keys[0]
}

/**
 * 功能: 校验 attach/detach 的所有权原语, 非法即 fail-fast.
 *
 * 为什么要在编译期拦: 载荷换父写错了(缺 id / dock 少一个分量)在运行期的表现是
 * "托盘悄悄不动"或"落位姿态整体转 90°", 既不报错也难归因 —— 与工具挂载缺
 * mount_transform 是同一类坑(见 three_d/docs/CLAUDE.md 第 32 条).
 *
 * @param {'attach'|'detach'} kind 原语名
 * @param {object} body 原语参数
 * @param {number} index 步骤下标(报错定位用)
 * @returns {void}
 * @throws {Error} 缺 id 或 dock 形状非法
 */
function validateOwnership(kind, body, index) {
  if (!body.id) throw new Error(`步骤 #${index} ${kind} 缺 id`)
  if (body.dock === undefined) return
  if (kind !== 'detach') throw new Error(`步骤 #${index} 只有 detach 支持 dock`)
  const { position, quaternion } = body.dock || {}
  if (!Array.isArray(position) || position.length !== 3
    || !Array.isArray(quaternion) || quaternion.length !== 4) {
    throw new Error(`步骤 #${index} detach.dock 必须是 {position:[3], quaternion:[4]}`)
  }
  // 严格判 number: YAML 的 null 经 Number() 是 0, 宽松判会把"缺一个分量"放行,
  // 表现是载荷落到 x=0 的原点上 —— 看着像"托盘飞走了", 查起来毫无线索。
  if ([...position, ...quaternion].some((value) => typeof value !== 'number' || !Number.isFinite(value))) {
    throw new Error(`步骤 #${index} detach.dock 含非有限数`)
  }
}

/** 标定值比对容差(mm): 零点写回时按 1e-3 mm 量化, 比它再严就是在比浮点噪声 */
const RAIL_CALIB_EPS_MM = 1e-6

/**
 * 功能: 判片段的地轨标定戳是否还与当前绑定契约一致 —— 片段陈旧检测.
 *
 * 为什么需要这条: 片段里的 `axis.to_mm` 是运行期换算的, 改标定跟着变; 但机械臂与
 * 载荷的落位(dock 位姿 / moveL 轨迹)是**编译期按当时的 axis_11y 标定烘死的**
 * (见 pipeline/scene_kinematics.RobotPosture)。标完零点不重编译片段, 那些落点就与
 * 新标定对不上, 而画面照播、**不报任何错**。
 *
 * 既有的 referencePointHash 校验抓不到它 —— clip 与 robot-points.json 出自同一次
 * 编译, 永远自洽, 一起陈旧时照样全绿。
 *
 * 判定**不致命**: 陈旧片段仍要能播(否则等于把演示页整个关掉), 只是要标出来。
 *
 * 调用约定: 手写片段没有 `source:` 段, 它们也从不含编译期烘焙 —— 那种情况传 null
 * (即 `doc.source ? doc.source.railCalib : null`), 别把"整个 source 段都没有"错当成
 * "编译器没打戳", 否则手写片段会常年挂着一个修不掉的「未标记」.
 *
 * @param {object|null|undefined} stamp 片段 source.railCalib(三态见 clip_compiler.rail_calib_stamp)
 * @param {object|null} manifest 当前 device-manifest
 * @returns {{state: 'ok'|'stale'|'unstamped'|'none', reason: string}} 判定
 */
export function railCalibStatus(stamp, manifest) {
  // 键缺失 = 打戳之前的编译器产物。**不许默认判绿** —— 那正是这套检测要堵的漏。
  if (stamp === undefined) {
    return { state: 'unstamped', reason: '片段未记录编译时的轴标定, 无法判定是否跟得上当前契约' }
  }
  // 显式 null = 编译时没有场景, 压根没烘任何落位, 无从陈旧
  if (stamp === null) return { state: 'none', reason: '' }

  const axisId = stamp.axis || 'axis_11y'
  const spec = (manifest?.axes || []).find((axis) => axis.id === axisId)
  if (!spec) {
    return { state: 'unstamped', reason: `当前契约里没有 ${axisId}, 无从比对` }
  }

  const drift = []
  if (Math.abs(Number(spec.zeroOffsetMm ?? 0) - Number(stamp.zeroOffsetMm ?? 0)) > RAIL_CALIB_EPS_MM) {
    drift.push(`零点 ${stamp.zeroOffsetMm} → ${spec.zeroOffsetMm}`)
  }
  if (Number(spec.sign ?? 1) !== Number(stamp.sign ?? 1)) {
    drift.push(`方向 ${stamp.sign} → ${spec.sign}`)
  }
  // range 也算: 它在烘焙公式里参与 clamp, 改了就可能改落点
  const nowRange = spec.rangeMm || [0, 0]
  const wasRange = stamp.rangeMm || [0, 0]
  if (nowRange.some((value, i) => Math.abs(Number(value) - Number(wasRange[i])) > RAIL_CALIB_EPS_MM)) {
    drift.push(`行程 [${wasRange}] → [${nowRange}]`)
  }

  if (!drift.length) return { state: 'ok', reason: '' }
  return {
    state: 'stale',
    reason: `${axisId} 标定已变(${drift.join('; ')}) —— 片段里的机械臂与载荷落点仍是旧标定烘的`,
  }
}

/**
 * 功能: 把 clip 文档编译为播放器可消费的关键帧表 + 事件表.
 *
 * 时间语义: 每步 `at` 缺省为**上一步(按声明顺序)的结束时刻**, 显式给 at 即可并行
 * (典型: 镜头与轴同时动). duration = 所有步的 max(at+dur).
 *
 * @param {object} doc parseClip 的产物
 * @param {object} [options] v2 外部事实源
 * @param {object} [options.pointCatalog] ptlc.robot-points/v1 目录
 * @returns {object} { name, label, duration, steps, channels, events }
 */
export function compileClip(doc, options = {}) {
  const home = doc.home || {}
  const homeAxes = home.axis_mm || {}
  const homeJoints = Array.isArray(home.joints_deg) ? home.joints_deg : [0, 0, 0, 0, 0, 0]
  const homeNodes = home.node_offset_m || {}
  const homeActuators = home.actuators || {}
  const homeLinkages = home.linkages || {}
  const homeLights = home.lights || {}
  // 单位写进键名: 液面通道存的是**毫升**不是 0..1, 键名叫 liquid 会被下一个人读成液位
  const homeLiquids = home.liquid_ml || {}
  // 注射泵同款纪律: pump_ml 存毫升(柱塞行程/液柱/丝杠都由它换算), pump_port 存 1 起数
  // 的端口号。两个 map 只在片段真的驱动了该泵时由编译器写入 —— 非泵片段一个键都没有。
  const homePumps = home.pump_ml || {}
  const homePumpPorts = home.pump_port || {}
  // 粉桶内容物同款纪律: powder_mm3 存**立方毫米**(高度由腔体自由截面积与观感放大系数换算,
  // 换算留在写入层), powder_tint 存 0..1 的洗脱色相位。粉的载体是跨片段搬运的桶 ——
  // 与 scrape 刻意相反(那条不设 home), 不声明起手态就是"收集-执行在演一只空桶"。
  const homePowderMm3 = home.powder_mm3 || {}
  const homePowderTint = home.powder_tint || {}

  /** @type {Map<string, Array<{t: number, v: number, ease: string}>>} */
  const channels = new Map()
  const keyframesOf = (key, initial) => {
    let list = channels.get(key)
    if (!list) {
      list = [{ t: 0, v: initial, ease: 'linear' }]
      channels.set(key, list)
    }
    return list
  }

  // home 里声明的连续量必须**各自成一条通道**, 哪怕本片段一步都没驱动它。
  //
  // 为什么: 向后 seek 与装载都走 `rig.home()`, 而那个函数把**每一根轴/机构**复位到 CAD
  // 基位并把值置 NaN(见 MachineStateDriver.home 的注释: 它是清场的唯一入口)。随后播放器
  // 只应用 clip 里**有通道**的量 —— 于是"只在 home 里声明、没有任何步骤"的量被静默丢掉,
  // 停在建模位。
  //
  // 这正是 clip_compiler.SEAT_AXES 那套机制的立足点: "片段自己不驱这些轴时, 就把它写进
  // home.axis_mm 声明成起手状态 —— 那不是编造运动, 板本来就在那个高度等着"。不建通道的话
  // 那句话是空的。2026-08-05 实测: 上样-上料的点样座 7Y 只在 home 里声明(该流程不动 7Y),
  // 于是板托座整段停在建模位, 而画面看着完全正常。
  for (const [id, value] of Object.entries(homeAxes)) keyframesOf(`axis:${id}`, Number(value))
  for (const [id, value] of Object.entries(homeActuators)) keyframesOf(`actuator:${id}`, Number(value))
  for (const [id, value] of Object.entries(homeLinkages)) keyframesOf(`linkage:${id}`, Number(value))
  for (const [id, value] of Object.entries(homeNodes)) {
    if (Array.isArray(value)) {
      value.forEach((component, axis) => keyframesOf(`node:${id}:${axis}`, Number(component)))
    }
  }
  // 液面尤其吃这一条, 但**方向与轴相反**: MachineStateDriver.home() 对液面不是
  // restoreLocal 而是一律 setLiquidMl(id, 0) 并隐藏液面盒(液面盒的建模位是满到槽口,
  // 那不是中性态, 空缸才是这台机器的静止态). 于是"只在 home.liquid_ml 里声明起手液量、
  // 片段自己不驱它的缸"(典型: 放板流程里那缸早已注好液)不建通道就会停在**空缸**.
  //
  // ⚠ 这里到 2026-08-06 为止写的是"不建通道就会停在满缸" —— 那是 home() 落地清零之前的
  // 事实, 早已作废. 照着它推会得出"不声明即满缸, 所以放板流程不用声明"的结论, 而那正是
  // 展开-上料把板放进空缸的由来(编译器侧的同源注释已一并订正).
  for (const [id, value] of Object.entries(homeLiquids)) keyframesOf(`liquid:${id}`, Number(value))
  // 泵与液面同理: home 声明的泵必须成通道, 否则 rig.home() 清零后"只声明不驱动"的泵
  // 会停在 0 而不是声明的起手液量(典型: 上一动作 prep 留下的 0.2mL 气隙)。
  for (const [id, value] of Object.entries(homePumps)) keyframesOf(`pump:${id}`, Number(value))
  for (const [id, value] of Object.entries(homePumpPorts)) keyframesOf(`pumpPort:${id}`, Number(value))
  // 粉与液面同理: home 声明的粉必须成通道, 否则 rig.home() 清零后"只声明不驱动"的桶
  // 会停在空桶而不是声明的起手粉量(典型: collect_unload 里桶是上一段 collect_execute
  // 洗脱后留下的, 本段一粒不吸但桶里得有货)。两条相位各建各的通道。
  for (const [id, value] of Object.entries(homePowderMm3)) keyframesOf(`powder:${id}:fill`, Number(value))
  for (const [id, value] of Object.entries(homePowderTint)) keyframesOf(`powder:${id}:tint`, Number(value))

  const events = []
  const steps = []
  let cursor = 0

  if (doc.schema === 'ptlc.clip/v2' || doc.schema === 'ptlc.clip/v3') {
    const expectedHash = doc.source?.referencePointHash
    const actualHash = options.pointCatalog?.referencePointHash
    if (!options.pointCatalog || options.pointCatalog.schema !== 'ptlc.robot-points/v1') {
      throw new Error(`${doc.schema} 需要 ptlc.robot-points/v1 点位目录`)
    }
    if (!expectedHash || expectedHash !== actualHash) {
      throw new Error(`clip/点表 SHA 不一致: clip=${expectedHash || '?'} catalog=${actualHash || '?'}`)
    }
  }

  doc.steps.forEach((raw, index) => {
    const at = raw.at !== undefined ? Number(raw.at) : cursor
    const dur = Math.max(0, Number(raw.dur ?? 0))
    const ease = raw.ease || 'inout'
    if (!(at >= 0) || !EASES[ease]) {
      throw new Error(`步骤 #${index} 的 at/ease 非法: at=${raw.at} ease=${ease}`)
    }
    const kind = primitiveOf(raw)
    const body = raw.do[kind]

    if (kind === 'axis') {
      if (!body.id || body.to_mm === undefined) throw new Error(`步骤 #${index} axis 缺 id/to_mm`)
      const list = keyframesOf(`axis:${body.id}`, Number(homeAxes[body.id] ?? 0))
      list.push({ t: at + dur, v: Number(body.to_mm), ease, from_t: at })
    } else if (kind === 'joints') {
      if (doc.schema !== 'ptlc.clip/v1' && doc.debug !== true) {
        throw new Error(`步骤 #${index} 的 joints.to_deg 仅允许 debug 片段使用`)
      }
      const target = body.to_deg
      if (!Array.isArray(target) || target.length !== 6) {
        throw new Error(`步骤 #${index} joints.to_deg 必须是长度 6 的数组(null=保持)`)
      }
      target.forEach((value, jointIndex) => {
        if (value === null || value === undefined) return
        const list = keyframesOf(`joint:${jointIndex}`, Number(homeJoints[jointIndex] ?? 0))
        list.push({ t: at + dur, v: Number(value), ease, from_t: at })
      })
    } else if (kind === 'robot_point') {
      if (doc.schema === 'ptlc.clip/v1') throw new Error(`步骤 #${index} robot_point 仅属于 clip/v2|v3`)
      const point = options.pointCatalog?.points?.[body.id]
      if (!point) throw new Error(`步骤 #${index} 找不到 robot_point: ${body.id}`)
      if (!point.allowedMotion?.includes(body.motion)) {
        throw new Error(`步骤 #${index} 点位 ${body.id} 不允许 ${body.motion}`)
      }

      if (body.motion === 'move_j') {
        const target = point.joint
        if (!Array.isArray(target) || target.length !== 6 || target.every((value) => Math.abs(value) < 1e-9)) {
          throw new Error(`步骤 #${index} 的 move_j 点位没有有效实测 joint: ${body.id}`)
        }
        target.forEach((value, jointIndex) => {
          const list = keyframesOf(`joint:${jointIndex}`, Number(homeJoints[jointIndex] ?? 0))
          list.push({ t: at + dur, v: Number(value), ease, from_t: at })
        })
      } else if (body.motion === 'move_l') {
        const trajectory = doc.compiled?.moveLTrajectories?.[String(index)]
        if (!Array.isArray(trajectory) || trajectory.length < 2) {
          throw new Error(`步骤 #${index} 的 move_l 缺少连续 IK 轨迹: ${body.id}`)
        }
        // 终点精确化: 离线轨迹按等距采样, 通常不含精确终点(实测取刀下插末样本离示教
        // 点 ~0.3°, 播放到底短少 ~0.5mm 再靠锁紧吸附兜底). 点位带实测 joint 时把末帧
        // 钉到示教值; 漂移过大说明轨迹与点表不同源, fail-fast 而不是静默硬拉.
        //
        // 例外: 编译器在 `compiled.staleJointPoints` 里点名的点, 它的实测 joint 与同一条
        // 记录的 pose **对不上**(吸附基准迁移只改了 pose, joint 没走示教闭环刷新;
        // 实测差着整整一个基准差 ~22mm)。这种点编译器已判定 pose 才是真的、按 pose 反解,
        // 那么再拿旧 joint 去核对轨迹终点必然报漂移 —— 两边都没错, 只是不该拿它当基准。
        // 这不是放宽门禁: 门禁仍对所有其它点生效, 而这几个点在片段里是**具名列出**的。
        const staleJoints = new Set(
          (doc.compiled?.staleJointPoints || []).map((item) => String(item?.point || '')),
        )
        const taught = Array.isArray(point.joint) && point.joint.length === 6
          && !point.joint.every((value) => Math.abs(value) < 1e-9)
          && !staleJoints.has(String(body.id))
          ? point.joint.map(Number)
          : null
        if (taught) {
          const last = trajectory[trajectory.length - 1]
          const drift = Math.max(
            ...taught.map((value, jointIndex) => Math.abs(value - Number(last?.[jointIndex]))),
          )
          if (drift > 1.5) {
            throw new Error(
              `步骤 #${index} 的 move_l 轨迹终点与点表漂移 ${drift.toFixed(2)}° (> 1.5°): `
              + `${body.id} —— 重新生成 clip`,
            )
          }
        }
        trajectory.forEach((jointValues, sampleIndex) => {
          if (!Array.isArray(jointValues) || jointValues.length !== 6) {
            throw new Error(`步骤 #${index} 的 move_l IK 样本非法: sample=${sampleIndex}`)
          }
          const isLast = sampleIndex === trajectory.length - 1
          const sampleTime = at + (dur * sampleIndex) / (trajectory.length - 1)
          jointValues.forEach((value, jointIndex) => {
            const list = keyframesOf(`joint:${jointIndex}`, Number(homeJoints[jointIndex] ?? 0))
            list.push({
              t: sampleTime,
              v: isLast && taught ? taught[jointIndex] : Number(value),
              ease: 'linear',
            })
          })
        })
      } else {
        throw new Error(`步骤 #${index} robot_point.motion 非法: ${body.motion}`)
      }
    } else if (kind === 'node') {
      if (!body.name || !Array.isArray(body.move)) throw new Error(`步骤 #${index} node 缺 name/move`)
      if (body.move.length !== 3) throw new Error(`步骤 #${index} node.move 必须为长度 3`)
      const initial = homeNodes[body.name] || [0, 0, 0]
      // 通用平移按三个分量各开一条通道；值是相对加载态的绝对偏移，不做累加。
      body.move.forEach((delta, axisIndex) => {
        const list = keyframesOf(`node:${body.name}:${axisIndex}`, Number(initial[axisIndex] || 0))
        list.push({ t: at + dur, v: Number(delta), ease, from_t: at })
      })
    } else if (kind === 'light') {
      // 灯是**连续通道**而不是离散事件, 这是刻意的: 通道值是 t 的纯函数, 拖进度条到
      // 任意时刻都能直接算出亮度, 不需要 ClipPlayer 的"回家重放"。补光本来就是
      // "渐亮 → 稳态 → 熄灭"的连续过程(真机 light_settle_ms 有 1s 稳定期), 做成
      // 离散开关既不像, 又会在 seek 时留下"该灭没灭"的残留状态。
      if (!body.id || body.to === undefined) throw new Error(`步骤 #${index} light 缺 id/to`)
      const to = Number(body.to)
      if (!Number.isFinite(to) || to < 0 || to > 1) {
        throw new Error(`步骤 #${index} light.to 必须是 0..1 的亮度系数, 实际: ${body.to}`)
      }
      const list = keyframesOf(`light:${body.id}`, Number(homeLights[body.id] ?? 0))
      list.push({ t: at + dur, v: to, ease, from_t: at })
    } else if (kind === 'liquid') {
      // 液面与灯同属**连续通道**, 理由逐条相同(见上一段): 值是 t 的纯函数, 拖进度条到
      // 任意时刻都算得出; 注/排液本来就是连续过程(实时侧画的就是 8~12 秒的趋近曲线),
      // 做成离散开关既不像, 又会在向后 seek 时留下"该空没空"的一整块可见体积.
      //
      // 通道值是**毫升**而不是 0..1 的液位: 液位要用 cavity 的实测自由截面积/槽深与
      // 观感放大系数换算, 而那三个数每跑一次 03 体素扫描都会变. 把它们烘进落盘片段的
      // 数字里, 重测一次全部片段就静默错位 —— 而 railCalibStatus 只盯轴标定, 没有任何
      // 指标会说它假. 毫升是动作入参里本来就有的数, 换算留到写入时做(setLiquidMl).
      //
      // 不设上界: 槽容 102mL 是**目标自己的**几何事实, schema 不知道也不该知道
      // (同一个原语将来还要驱 25mL 的注射器液柱), 溢出在写入时按各自容量夹.
      if (!body.id || body.to_ml === undefined) throw new Error(`步骤 #${index} liquid 缺 id/to_ml`)
      const toMl = Number(body.to_ml)
      if (!Number.isFinite(toMl) || toMl < 0) {
        throw new Error(`步骤 #${index} liquid.to_ml 必须是非负毫升数, 实际: ${body.to_ml}`)
      }
      const list = keyframesOf(`liquid:${body.id}`, Number(homeLiquids[body.id] ?? 0))
      list.push({ t: at + dur, v: toMl, ease, from_t: at })
    } else if (kind === 'scrape') {
      // 刮取进度与灯/液面同属**连续通道**(理由同上两段): 已刮/已收前沿是 t 的纯函数,
      // 拖进度条到任意时刻都算得出, 不靠"回家重放"。两条相位各自成通道:
      //   loosen —— 刮刀刮松粉层的前沿(0..1, 沿条带推进);
      //   clear  —— 粉桶收走粉、露出玻璃的前沿(0..1, 方向可与 loosen 相反)。
      // 单通道+固定滞后表达不了真机时序(收集是刮完后平移 90mm 再反向回扫)。
      //
      // 通道值是 0..1 的**前沿进度**而不是毫米: 条带矩形(板 cm 帧)由编译器算好放在
      // compiled.scrapeRegions, 播放器只透传; 几何换算(cm→板 UV)留到写入层按当帧
      // 板姿态做(PlateStage.setScrape), 与 liquid 的"换算留写入层"同一条纪律。
      //
      // ⚠ 刻意**不设 home 段**(不照抄 liquid 的 homeLiquids): 刮取的中性态就是 0
      // (未刮), 与"液面盒建模位=满到槽口"那种非中性建模位不同 —— 片段起手永远从
      // 未刮开始, "起手进度"没有物理对应物, 补上只会诱导下一个人编造它。
      // 2026-08-06 加第三条相位 `pass` —— 分层刮取(真机 num_passes 刀, 每刀只吃
      // total_depth/N)。它是**层号**(1 起数)而不是 0..1 进度: 剩余厚度要用层号和
      // 总层数换算, 而总层数是编译期产物(compiled.scrapeRegions[id].passes),
      // 与"条带矩形留在 region、通道只带进度"同一条分工。
      // 三条相位合起来才够画: clear 前沿之后 = 第 pass 层, 之前 = 第 pass−1 层,
      // loosen 前沿之内叠"刮松未收"的色 —— 单条通道表达不了空间上两级深度并存。
      if (!body.id || !body.phase || body.to === undefined) {
        throw new Error(`步骤 #${index} scrape 缺 id/phase/to`)
      }
      if (!['loosen', 'clear', 'pass'].includes(body.phase)) {
        throw new Error(`步骤 #${index} scrape.phase 必须是 loosen / clear / pass, 实际: ${body.phase}`)
      }
      const to = Number(body.to)
      if (body.phase === 'pass') {
        if (!Number.isInteger(to) || to < 0) {
          throw new Error(`步骤 #${index} scrape.to(pass 相位) 必须是 ≥0 的整数层号, 实际: ${body.to}`)
        }
      } else if (!Number.isFinite(to) || to < 0 || to > 1) {
        throw new Error(`步骤 #${index} scrape.to 必须是 0..1 的进度, 实际: ${body.to}`)
      }
      const list = keyframesOf(`scrape:${body.id}:${body.phase}`, 0)
      list.push({ t: at + dur, v: to, ease, from_t: at })
    } else if (kind === 'spot') {
      // 点样色带渐现, 与 scrape 同属连续通道(进度是 t 的纯函数, 拖进度条随处可算)。
      // 通道值是 0..1 的**渐现进度**而不是毫米: 条带矩形(板 cm 帧)由编译器算好放在
      // compiled.spotRegions, 播放器只透传 —— 与"条带留在 region、通道只带进度"的
      // scrape 分工逐字相同。band 是 1 起数的条带号: 多样品多条带各自成通道、各自渐现。
      // 同理不设 home 段: 中性态就是 0(未点样), "起手进度"没有物理对应物。
      if (!body.id || body.to === undefined) throw new Error(`步骤 #${index} spot 缺 id/to`)
      const band = body.band === undefined ? 1 : Number(body.band)
      if (!Number.isInteger(band) || band < 1) {
        throw new Error(`步骤 #${index} spot.band 必须是 ≥1 的整数条带号, 实际: ${body.band}`)
      }
      const to = Number(body.to)
      if (!Number.isFinite(to) || to < 0 || to > 1) {
        throw new Error(`步骤 #${index} spot.to 必须是 0..1 的进度, 实际: ${body.to}`)
      }
      const list = keyframesOf(`spot:${body.id}:band${band}`, 0)
      list.push({ t: at + dur, v: to, ease, from_t: at })
    } else if (kind === 'wet') {
      // 溶剂润湿前沿(展开), 同上一族。通道值是 0..1 的**前沿进度**而不是液位百分比:
      // 展开中没有"板面高度"的真值(液位视觉给的是 ROI 百分比, 无 cm 映射), 前沿目标
      // 高度是编译器的显式演示假设, 放 compiled.wetRegions 不烘进通道 —— 假设改了
      // 只动 region, 片段通道不陈旧。
      if (!body.id || body.to === undefined) throw new Error(`步骤 #${index} wet 缺 id/to`)
      const to = Number(body.to)
      if (!Number.isFinite(to) || to < 0 || to > 1) {
        throw new Error(`步骤 #${index} wet.to 必须是 0..1 的进度, 实际: ${body.to}`)
      }
      const list = keyframesOf(`wet:${body.id}`, 0)
      list.push({ t: at + dur, v: to, ease, from_t: at })
    } else if (kind === 'spindle') {
      // 主轴(铣刀自转)。通道值是 **0/1 的开关**, 不是转角 —— 转角是无限增长量,
      // 表达不成 t 的纯函数, 而"通道值必须是 t 的纯函数"是本 schema 的地基
      // (向后 seek 靠它免于重放)。相位由 MachineStateDriver.updateSpindles 逐帧按
      // manifest 的 rpm 累加, 与补光的 setFlash 同属**渲染层装饰**, home() 时清零。
      //
      // 阶跃而非渐变: 真机主轴的起停有升降速, 但屏幕上分辨不出 —— 而把 ease 留给
      // 调用方会诱导人写"转速渐变", 那需要相位对时间积分, 又回到不是纯函数的老路。
      // 故这里固定 ease: 'step', 忽略调用方给的 ease。
      if (!body.id || body.on === undefined) throw new Error(`步骤 #${index} spindle 缺 id/on`)
      const on = body.on === true || Number(body.on) === 1 ? 1 : 0
      const list = keyframesOf(`spindle:${body.id}`, 0)
      list.push({ t: at + dur, v: on, ease: 'step', from_t: at })
    } else if (kind === 'pump') {
      // 与 liquid 同属连续通道且同单位纪律: 值是毫升, 不设上界(25mL 是针筒自己的几何
      // 事实, 溢出在写入时按 manifest 的 syringeMl 夹, 见 setPumpMl)。
      if (!body.id || body.to_ml === undefined) throw new Error(`步骤 #${index} pump 缺 id/to_ml`)
      const toMl = Number(body.to_ml)
      if (!Number.isFinite(toMl) || toMl < 0) {
        throw new Error(`步骤 #${index} pump.to_ml 必须是非负毫升数, 实际: ${body.to_ml}`)
      }
      const list = keyframesOf(`pump:${body.id}`, Number(homePumps[body.id] ?? 0))
      list.push({ t: at + dur, v: toMl, ease, from_t: at })
    } else if (kind === 'pump_valve') {
      // 通道值是**端口号**(1 起数)而不是角度: 各端口的指针角是 03 程序化建模的产物
      // (valvePortAngles), 每重跑一次就变, 烘进片段即陈旧。端口弧在一条单调弧段上
      // (335°→205°), 端口空间线性插值与实时侧的最短路径转动观感一致。
      if (!body.id || body.port === undefined) throw new Error(`步骤 #${index} pump_valve 缺 id/port`)
      const port = Number(body.port)
      if (!Number.isInteger(port) || port < 1) {
        throw new Error(`步骤 #${index} pump_valve.port 必须是 ≥1 的整数端口号, 实际: ${body.port}`)
      }
      const list = keyframesOf(`pumpPort:${body.id}`, Number(homePumpPorts[body.id] ?? 1))
      list.push({ t: at + dur, v: port, ease, from_t: at })
    } else if (kind === 'powder') {
      // 粉柱(粉桶内容物)与液面同属连续通道: 值是 t 的纯函数, 拖进度条到任意时刻都算得出。
      // 单位是**立方毫米**(mm³)而不是液位 0..1: 高度要用腔体实测自由截面积与观感放大系数
      // 换算 —— 与 liquid 的"换算留写入层"同一条纪律。
      //
      // 两条相位各自成通道, 但它们是**同一件物**的两个自由度、必须成对写入:
      //   fill —— 桶内粉量, to **不设上界**(腔容是目标自己的几何事实, 溢出在写入时按
      //           manifest 的 capacityMm3 自然饱和到液位 1.0);
      //   tint —— 洗脱色相位 0..1(未洗 0 / 洗后 1)。它是**相位不是独立原语**: 拆开会让
      //           写序取决于 Object.entries 的枚举序, 而账本侧 powder_mm3 与 eluted 也在
      //           同一行 —— 粉量与颜色本来就是一个状态的两个面。
      if (!body.id || !body.phase || body.to === undefined) {
        throw new Error(`步骤 #${index} powder 缺 id/phase/to`)
      }
      if (!['fill', 'tint'].includes(body.phase)) {
        throw new Error(`步骤 #${index} powder.phase 必须是 fill / tint, 实际: ${body.phase}`)
      }
      const to = Number(body.to)
      if (body.phase === 'tint') {
        if (!Number.isFinite(to) || to < 0 || to > 1) {
          throw new Error(`步骤 #${index} powder.to(tint 相位) 必须是 0..1 的洗脱色相位, 实际: ${body.to}`)
        }
      } else if (!Number.isFinite(to) || to < 0) {
        throw new Error(`步骤 #${index} powder.to(fill 相位) 必须是非负 mm³, 实际: ${body.to}`)
      }
      const initial = body.phase === 'fill'
        ? Number(homePowderMm3[body.id] ?? 0)
        : Number(homePowderTint[body.id] ?? 0)
      const list = keyframesOf(`powder:${body.id}:${body.phase}`, initial)
      list.push({ t: at + dur, v: to, ease, from_t: at })
    } else if (kind === 'actuator' || kind === 'linkage') {
      if (!body.id || (body.to === undefined && body.value === undefined)) {
        throw new Error(`步骤 #${index} ${kind} 缺 id/to`)
      }
      const initialMap = kind === 'actuator' ? homeActuators : homeLinkages
      const list = keyframesOf(`${kind}:${body.id}`, Number(initialMap[body.id] ?? 0))
      list.push({ t: at + dur, v: Number(body.to ?? body.value), ease, from_t: at })
    } else if (['tool', 'attach', 'detach', 'state', 'camera', 'highlight', 'plate'].includes(kind)) {
      if (kind === 'attach' || kind === 'detach') validateOwnership(kind, body, index)
      if (kind === 'plate') validatePlateStep(body, index)
      events.push({ t: at, kind, payload: { ...body }, step: index })
    } // wait: 只占时间

    steps.push({
      index,
      label: raw.label || kind,
      at,
      dur,
      end: at + dur,
      kind,
    })
    cursor = at + dur
  })

  // 关键帧补 from_t: 每个目标帧从 from_t 开始起步, 之前保持上一帧的值 ——
  // 实现方式是在 from_t 处插入一个"保持帧", 求值时只需相邻帧插值
  for (const list of channels.values()) {
    list.sort((a, b) => a.t - b.t)
    for (let i = list.length - 1; i >= 1; i -= 1) {
      const frame = list[i]
      if (frame.from_t === undefined) continue
      const prevValue = list[i - 1].v
      if (frame.from_t > list[i - 1].t + 1e-9) {
        list.splice(i, 0, { t: frame.from_t, v: prevValue, ease: 'linear' })
      }
      delete frame.from_t
    }
  }

  events.sort((a, b) => a.t - b.t || a.step - b.step)
  const duration = Math.max(...steps.map((step) => step.end), 0)

  return {
    schema: doc.schema,
    name: doc.name || 'clip',
    label: doc.label || doc.name || 'clip',
    description: doc.description || '',
    duration,
    home: {
      axes: { ...homeAxes },
      joints: [...homeJoints],
      nodes: { ...homeNodes },
      actuators: { ...homeActuators },
      linkages: { ...homeLinkages },
      lights: { ...homeLights },
      liquids: { ...homeLiquids },
      pumps: { ...homePumps },
      pumpPorts: { ...homePumpPorts },
      // 粉是**一件物的两个自由度**, 故不是两张平铺 map 而是一张 {mm3, tint} ——
      // 消费方(evaluateChannels / MachineStateDriver.updatePowders)拿到的永远是成对的。
      powders: { mm3: { ...homePowderMm3 }, tint: { ...homePowderTint } },
    },
    steps,
    channels,
    events,
    source: doc.source || null,
    operation: doc.operation || null,
    // 编译期把决策外壳拍平的地方(取了哪个分支、循环只编了第几轮)。几何是精确的, **路线
    // 不是** —— 不把它带到界面上, "精编译"三个字会被读成"这就是实况"。
    flowNotes: Array.isArray(doc.flowNotes) ? [...doc.flowNotes] : [],
    // 痕迹几何(板 cm 帧) —— "编译器算好、播放器照用"的产物与 moveLTrajectories
    // 同住片段的 compiled: 块, 这里透传给 ClipPlayer 按 id 发放。
    scrapeRegions: doc.compiled?.scrapeRegions || null,
    spotRegions: doc.compiled?.spotRegions || null,
    wetRegions: doc.compiled?.wetRegions || null,
  }
}

/**
 * 功能: 求 t 时刻全部连续通道的值(纯函数, seek 安全).
 * @param {object} compiled compileClip 产物
 * @param {number} t 时刻(秒)
 * @returns {{axes: Object<string, number>, joints: number[], nodes: Object<string, number[]>,
 *            actuators: Object<string, number>, linkages: Object<string, number>,
 *            lights: Object<string, number>, liquids: Object<string, number>,
 *            scrapes: Object<string, {loosen: number, clear: number}>,
 *            pumps: Object<string, number>, pumpPorts: Object<string, number>,
 *            powders: Object<string, {fill: number, tint: number}>}}
 *          liquids/pumps 单位是 mL, pumpPorts 是 1 起数的端口号(过渡期间可为小数),
 *          powders 的 fill 单位是 mm³、tint 是 0..1 洗脱色相位(换算一律留在写入层)
 */
export function evaluateChannels(compiled, t) {
  const axes = {}
  const joints = [...compiled.home.joints]
  const nodes = {}
  const actuators = { ...(compiled.home.actuators || {}) }
  const linkages = { ...(compiled.home.linkages || {}) }
  const lights = { ...(compiled.home.lights || {}) }
  const liquids = { ...(compiled.home.liquids || {}) }
  const scrapes = {}
  // 主轴与三种板面痕迹同理**不设 home 段**: 中性态就是停转/净板
  const spindles = {}
  const spots = {}
  const wets = {}
  const pumps = { ...(compiled.home.pumps || {}) }
  const pumpPorts = { ...(compiled.home.pumpPorts || {}) }
  // 粉按 id 汇成 {fill, tint} 成对交付。播种取 home 的两张声明 map 并成一张:
  // 只声明了粉量没声明色的桶(常态)照样有 tint: 0, 消费方不必到处判 undefined。
  const powders = {}
  const homePowders = compiled.home.powders || {}
  for (const [id, mm3] of Object.entries(homePowders.mm3 || {})) {
    powders[id] = { fill: Number(mm3) || 0, tint: 0 }
  }
  for (const [id, tint] of Object.entries(homePowders.tint || {})) {
    if (!powders[id]) powders[id] = { fill: 0, tint: 0 }
    powders[id].tint = Number(tint) || 0
  }

  for (const [key, frames] of compiled.channels) {
    const value = sampleChannel(frames, t)
    if (key.startsWith('axis:')) {
      axes[key.slice(5)] = value
    } else if (key.startsWith('joint:')) {
      joints[Number(key.slice(6))] = value
    } else if (key.startsWith('node:')) {
      const lastColon = key.lastIndexOf(':')
      const name = key.slice(5, lastColon)
      const axisIndex = key.slice(lastColon + 1)
      if (!nodes[name]) nodes[name] = [0, 0, 0]
      nodes[name][Number(axisIndex)] = value
    } else if (key.startsWith('actuator:')) {
      actuators[key.slice(9)] = value
    } else if (key.startsWith('linkage:')) {
      linkages[key.slice(8)] = value
    } else if (key.startsWith('light:')) {
      lights[key.slice(6)] = value
    } else if (key.startsWith('liquid:')) {
      liquids[key.slice(7)] = value
    } else if (key.startsWith('scrape:')) {
      // 键形如 scrape:<id>:<phase>。照 node 的写法从右侧拆相位, 不对 id 字符集做假设
      // (片段里的板恒叫 "plate", 但这不是本函数该依赖的事实)。
      const lastColon = key.lastIndexOf(':')
      const id = key.slice(7, lastColon)
      const phase = key.slice(lastColon + 1)
      // 缺省只播种 loosen/clear 两条 —— `pass` **有意留空**: 分层之前编出来的片段没有
      // 这条通道, 写入层据此认出"老片段"并按单刀语义处理(clear 到底即露玻璃)。
      // 给 pass 播个 0 会让老片段变成"永远刮不透"。
      if (!scrapes[id]) scrapes[id] = { loosen: 0, clear: 0 }
      scrapes[id][phase] = value
    } else if (key.startsWith('spindle:')) {
      spindles[key.slice(8)] = value
    } else if (key.startsWith('spot:')) {
      // 键形如 spot:<id>:band<N>。照 scrape 的写法从右侧拆条带号, 不对 id 字符集做假设
      const lastColon = key.lastIndexOf(':')
      const id = key.slice(5, lastColon)
      const band = Number(key.slice(lastColon + 1).replace('band', ''))
      if (!spots[id]) spots[id] = {}
      spots[id][band] = value
    } else if (key.startsWith('wet:')) {
      wets[key.slice(4)] = value
    } else if (key.startsWith('pumpPort:')) {
      // 先于 'pump:' 判: 两个前缀共享头四个字符, 顺序反了 pumpPort 通道会被当成
      // id 为 "Port:<id>" 的 pump 通道悄悄吞掉。
      pumpPorts[key.slice(9)] = value
    } else if (key.startsWith('pump:')) {
      pumps[key.slice(5)] = value
    } else if (key.startsWith('powder:')) {
      // 键形如 powder:<id>:<phase>。照 scrape 的写法从右侧拆相位, 不对 id 字符集做假设。
      const lastColon = key.lastIndexOf(':')
      const id = key.slice(7, lastColon)
      const phase = key.slice(lastColon + 1)
      // 缺省播种 fill/tint 都播 0 —— 与 scrape 的 pass **不同**: 未洗(0)才是粉的中性态,
      // 老片段(没有 tint 通道)播 0 是正确的"未洗", 不是像 pass=0 那样让老片段永远刮不透。
      // "洗过"的真值由 home.powder_tint 播种声明(通道播种在 compileClip 里)。
      if (!powders[id]) powders[id] = { fill: 0, tint: 0 }
      powders[id][phase] = value
    }
  }
  return { axes, joints, nodes, actuators, linkages, lights, liquids, scrapes, spindles, spots, wets, pumps, pumpPorts, powders }
}

/**
 * 功能: 在一条通道的关键帧序列上采样.
 * @param {Array<{t: number, v: number, ease: string}>} frames 关键帧(按 t 升序)
 * @param {number} t 时刻
 * @returns {number} 通道值
 */
export function sampleChannel(frames, t) {
  if (t <= frames[0].t) return frames[0].v
  for (let i = 1; i < frames.length; i += 1) {
    const next = frames[i]
    if (t < next.t) {
      const prev = frames[i - 1]
      const span = next.t - prev.t
      const progress = span > 1e-9 ? (t - prev.t) / span : 1
      const eased = (EASES[next.ease] || EASES.linear)(progress)
      return prev.v + (next.v - prev.v) * eased
    }
  }
  return frames[frames.length - 1].v
}

/**
 * 功能: 取 t 时刻(含)之前的全部离散事件 —— seek 的"回家重放"用它.
 * @param {object} compiled compileClip 产物
 * @param {number} t 时刻
 * @returns {object[]} 事件数组(按时间序)
 */
export function eventsUpTo(compiled, t) {
  return compiled.events.filter((event) => event.t <= t + 1e-9)
}

/**
 * 功能: 求 t 时刻处于哪一步(供 UI 高亮当前步骤).
 * @param {object} compiled compileClip 产物
 * @param {number} t 时刻
 * @returns {number} 步骤下标; 不在任何步内则返回最近开始过的一步
 */
export function stepIndexAt(compiled, t) {
  let current = 0
  for (const step of compiled.steps) {
    if (step.at <= t + 1e-9) current = step.index
    if (step.at <= t && t < step.end) return step.index
  }
  return current
}
