/**
 * 功能: 视口内 1-DOF 轴拖拽的正确性单测 —— 方向与增益必须与相机距离(缩放)无关.
 *
 * 值得单测的理由: 拖拽是 rig_map 里 `sign` 的**判定工具**. AXIS_ZERO_CALIBRATION 的
 * 七步法第 2 步就是"jog 看虚拟动向, 反了就翻 sign", 而 axis_3y/axis_5z 的 sign 注释
 * 白纸黑字记着"2026-08-02 用户在动作界面实拖判定与真机反向, 取反为 +1". 拖拽自己
 * 会随缩放翻向的话, 判出来的 sign 就是错的, 而且会被固化进 YAML 传给现场 ——
 * 这条测的价值不在 UI 手感, 在于保护标定数据的可信度.
 *
 * 判据设计: 把指针从 `screenOf(抓取点)` 拖到 `screenOf(抓取点 + 轴向·Δ米)`,
 * 那么轴应当**恰好**走 Δ 米对应的毫米数 —— 这个往返判据与相机距离、透视缩率无关,
 * 是"跟手"的精确定义. 三档相机距离(minDistance / 默认 iso / maxDistance)各测一遍,
 * 方向与幅度都必须一致.
 */
import assert from 'node:assert/strict'
import test from 'node:test'

import * as THREE from 'three'

import { axisUnitPerMm } from '../../src/three-d/anim/MachineStateDriver.js'
import { AxisDragController } from '../../src/three-d/motion/AxisDragController.js'

// AxisDragController 在 _bind 里挂 window 的 keydown; node 环境没有 window
if (typeof globalThis.window === 'undefined') {
  globalThis.window = { addEventListener() {}, removeEventListener() {} }
}

/** 整机外接球半径(2.64×2.10×1.53 m 的对角线一半), CameraRig 用它推所有相机参数 */
const MODEL_RADIUS = 1.85
const FOV = 42
const ASPECT = 16 / 9
const CANVAS = { left: 0, top: 0, width: 1600, height: 900 }

/** CameraRig 的三档距离: minDistance / applyPreset('iso') / maxDistance */
const DISTANCES = {
  near: MODEL_RADIUS * 0.12,
  iso: (MODEL_RADIUS / Math.sin(THREE.MathUtils.degToRad(FOV) / 2)) * 0.82,
  far: MODEL_RADIUS * 12,
}

/** VIEW_PRESETS.iso */
const VIEW_DIR = new THREE.Vector3(1.0, 0.72, 1.25).normalize()

/**
 * 功能: 搭一套最小可拖场景 + 桩 manager/rig, 语义与真实 MotionView 一致.
 * @param {object} opts 参数
 * @param {number[]} opts.axis 轴向(父局部系, 与 manifest 的 axes[].axis 同义)
 * @param {number} opts.distance 相机到轴原点的距离
 * @param {number} [opts.sign=1] 伺服正方向
 * @param {number} [opts.polarDeg] 相机极角(度, 0=正俯视); 省略则用 VIEW_PRESETS.iso 方向
 * @returns {object} harness
 */
function makeHarness({ axis, distance, sign = 1, polarDeg = null, scaleMm = 1 }) {
  const scene = new THREE.Scene()
  const root = new THREE.Object3D()
  scene.add(root)

  // 轴节点: 枢轴在零位(与 blender_clean 建 AXIS_*/CARRIAGE 的约定一致)
  const axisNode = new THREE.Object3D()
  axisNode.name = 'AXIS_AXIS_TEST'
  root.add(axisNode)

  // 可拖网格**偏离轴线**放置 —— 真实滑车零件从不正好骑在枢轴上, 而这个偏移量
  // 正是"最近点解"在近距相机下失准的来源, 不能省
  const mesh = new THREE.Mesh(new THREE.BoxGeometry(0.05, 0.05, 0.05))
  mesh.position.set(0.03, 0.01, 0.02)
  axisNode.add(mesh)

  const camera = new THREE.PerspectiveCamera(
    FOV,
    ASPECT,
    Math.max(MODEL_RADIUS / 800, 0.01),
    MODEL_RADIUS * 40,
  )
  if (polarDeg === null) {
    camera.position.copy(VIEW_DIR).multiplyScalar(distance)
  } else {
    const p = THREE.MathUtils.degToRad(polarDeg)
    camera.position.set(
      Math.sin(p) * Math.cos(0.9) * distance,
      Math.cos(p) * distance,
      Math.sin(p) * Math.sin(0.9) * distance,
    )
  }
  camera.lookAt(0, 0, 0)
  camera.updateMatrixWorld(true)
  scene.updateMatrixWorld(true)

  const handlers = new Map()
  const canvas = {
    style: {},
    addEventListener: (type, fn) => handlers.set(type, fn),
    removeEventListener: (type) => handlers.delete(type),
    setPointerCapture() {},
    releasePointerCapture() {},
    getBoundingClientRect: () => ({ ...CANVAS, right: CANVAS.width, bottom: CANVAS.height }),
  }

  const spec = {
    axis: [...axis],
    sign,
    // 控制侧 mm → 物理 mm 的增益(manifest 的 axes[].scaleMm)。缺省 1;
    // 真机上只有 axis_4x 是 2.0(自制同步带 + 步进, 标度配成了一半)。
    scaleMm,
    mmToUnit: 0.001,
    rangeMm: [-10000, 10000], // 本测不验 clamp, 放宽避免饱和掩盖方向错误
    zeroOffsetMm: 0,
  }
  const entry = {
    node: axisNode,
    base: axisNode.position.clone(),
    direction: new THREE.Vector3(...axis).normalize(),
    spec,
    valueMm: 0,
  }

  const rig = {
    axes: new Map([['axis_test', entry]]),
    // 镜像 MachineStateDriver.setAxisMm。**换算直接用生产代码的 axisUnitPerMm**,
    // 不在这里重抄一遍 —— 桩与生产各写各的正是"一乘一除迟早漂"的温床。
    setAxisMm(id, mm) {
      const e = this.axes.get(id)
      if (!e || !Number.isFinite(Number(mm))) return false
      const [lo, hi] = e.spec.rangeMm
      const value = Math.min(Math.max(Number(mm), lo), hi)
      const offset = (value - e.spec.zeroOffsetMm) * axisUnitPerMm(e.spec)
      e.node.position.copy(e.base).addScaledVector(e.direction, offset)
      e.node.updateMatrixWorld(true)
      e.valueMm = value
      return true
    },
  }

  const manager = {
    canvas,
    camera,
    scene,
    cameraRig: { controls: { enabled: true } },
    invalidateShadows() {},
  }

  const controller = new AxisDragController({ manager, rig })

  /** 世界点 -> 画布客户端像素(与 MotionView.__motion.screenOf 同式) */
  const screenOf = (world) => {
    const v = world.clone().project(camera)
    return {
      clientX: CANVAS.left + ((v.x + 1) / 2) * CANVAS.width,
      clientY: CANVAS.top + ((1 - v.y) / 2) * CANVAS.height,
    }
  }

  /** 指针射线命中网格的表面点 —— 即用户真正"抓住"的那个点 */
  const grabPoint = () => {
    const center = new THREE.Vector3()
    mesh.getWorldPosition(center)
    const at = screenOf(center)
    const ndc = new THREE.Vector2(
      ((at.clientX - CANVAS.left) / CANVAS.width) * 2 - 1,
      -((at.clientY - CANVAS.top) / CANVAS.height) * 2 + 1,
    )
    const ray = new THREE.Raycaster()
    ray.setFromCamera(ndc, camera)
    const hits = ray.intersectObject(mesh, false)
    assert.ok(hits.length, '测试装置自身有问题: 指针射线没打中可拖网格')
    return hits[0].point.clone()
  }

  const fire = (type, at) => handlers.get(type)?.({ button: 0, pointerId: 1, ...at })

  return { controller, entry, rig, camera, mesh, screenOf, grabPoint, fire }
}

/**
 * 功能: 从抓取点沿轴向拖 deltaM 米, 返回轴最终的毫米值.
 * @param {object} h harness
 * @param {number} deltaM 期望的世界位移(米, 沿 entry.direction 正向)
 * @returns {number} 轴值 mm
 */
function dragAlongAxis(h, deltaM) {
  const from = h.grabPoint()
  const to = from.clone().addScaledVector(h.entry.direction, deltaM)
  h.fire('pointerdown', h.screenOf(from))
  h.fire('pointermove', h.screenOf(to))
  h.fire('pointerup', h.screenOf(to))
  return h.entry.valueMm
}

// 沿轴走 deltaM 米 = deltaM/(sign·scaleMm·mmToUnit) 毫米
const expectedMm = (deltaM, sign = 1, scaleMm = 1) => deltaM / (sign * scaleMm * 0.001)

// 判据是精确往返, 容差只留给浮点与射线求交; 旧的最近点解在近距档会差数毫米
const TOL_MM = 0.5

const AXES = {
  '5Z(竖直, glTF Y)': [0, 1, 0],
  '6X(水平, glTF Z)': [0, 0, 1],
  '4X(水平, glTF X)': [1, 0, 0],
}

for (const [label, axis] of Object.entries(AXES)) {
  for (const [zoom, distance] of Object.entries(DISTANCES)) {
    for (const deltaM of [0.02, -0.02]) {
      test(`拖拽跟手: ${label} @ ${zoom}(${distance.toFixed(3)}m) Δ=${deltaM}m`, () => {
        const h = makeHarness({ axis, distance })
        const mm = dragAlongAxis(h, deltaM)
        const want = expectedMm(deltaM)
        assert.ok(
          Math.abs(mm - want) <= TOL_MM,
          `期望 ${want.toFixed(2)}mm, 实得 ${mm.toFixed(2)}mm (偏差 ${(mm - want).toFixed(2)}mm)`,
        )
      })
    }
  }
}

// scaleMm ≠ 1 的轴(真机上是 axis_4x=2.0: 控制侧 1mm = 物理 2mm)。
// 拖同样的物理距离, 读数应当**只有一半** —— 因为那根轴的"毫米"本身就是半毫米。
// 这条锁的是"一乘一除同源": 若 AxisDragController 忘了除 scaleMm(或 setAxisMm 忘了乘),
// 拖拽读数会差整整一倍, 而画面看着仍在动、不报任何错。
for (const [label, axis] of Object.entries(AXES)) {
  for (const [zoom, distance] of Object.entries(DISTANCES)) {
    test(`增益 scaleMm=2 时拖拽读数减半: ${label} @ ${zoom}`, () => {
      const h = makeHarness({ axis, distance, scaleMm: 2 })
      const mm = dragAlongAxis(h, 0.02)
      const want = expectedMm(0.02, 1, 2)          // 0.02m / (1·2·0.001) = 10mm
      assert.ok(
        Math.abs(mm - want) <= TOL_MM,
        `scaleMm=2 期望 ${want.toFixed(2)}mm, 实得 ${mm.toFixed(2)}mm`,
      )
      // 与 scaleMm=1 的同一次拖拽相比恰好一半(不靠常数, 直接对比两次运行)
      const base = dragAlongAxis(makeHarness({ axis, distance }), 0.02)
      assert.ok(
        Math.abs(mm * 2 - base) <= TOL_MM * 2,
        `scaleMm=2 的读数应是 scaleMm=1 的一半: ${mm.toFixed(2)} vs ${base.toFixed(2)}`,
      )
    })
  }
}

// 增益也必须真的作用到**位移**上(不只是读数): 同一个 mm 目标, scaleMm=2 走两倍距离。
test('增益作用于位移: 同一 mm 目标, scaleMm=2 的位移是 1 的两倍', () => {
  const axis = [0, 0, 1]
  const h1 = makeHarness({ axis, distance: DISTANCES.iso })
  const h2 = makeHarness({ axis, distance: DISTANCES.iso, scaleMm: 2 })
  h1.rig.setAxisMm('axis_test', 10)
  h2.rig.setAxisMm('axis_test', 10)
  const d1 = h1.entry.node.position.distanceTo(h1.entry.base)
  const d2 = h2.entry.node.position.distanceTo(h2.entry.base)
  assert.ok(
    Math.abs(d2 - 2 * d1) < 1e-9,
    `期望 ${(2 * d1).toFixed(6)}m, 实得 ${d2.toFixed(6)}m`,
  )
})

test('拖拽方向不随相机距离翻转(三档同号)', () => {
  for (const [label, axis] of Object.entries(AXES)) {
    const signs = Object.entries(DISTANCES).map(([zoom, distance]) => {
      const mm = dragAlongAxis(makeHarness({ axis, distance }), 0.02)
      return { zoom, mm, sign: Math.sign(mm) }
    })
    const uniq = new Set(signs.map((s) => s.sign))
    assert.equal(
      uniq.size,
      1,
      `${label} 三档缩放拖动方向不一致: ${signs.map((s) => `${s.zoom}=${s.mm.toFixed(1)}mm`).join(', ')}`,
    )
  }
})

test('sign=-1 时拖拽仍跟手(位移方向由 sign 与 axis 共同决定)', () => {
  for (const [, axis] of Object.entries(AXES)) {
    for (const [, distance] of Object.entries(DISTANCES)) {
      const h = makeHarness({ axis, distance, sign: -1 })
      // direction 是几何轴向, sign 只改 mm->位移 的换算, 故沿 +direction 拖 0.02m
      // 对应的 mm 值是负的
      const mm = dragAlongAxis(h, 0.02)
      assert.ok(
        Math.abs(mm - expectedMm(0.02, -1)) <= TOL_MM,
        `sign=-1 期望 ${expectedMm(0.02, -1)}mm, 实得 ${mm.toFixed(2)}mm`,
      )
    }
  }
})

test('分步拖拽全程单调, 无分支跳变(覆盖 s0 播种坑)', () => {
  for (const [label, axis] of Object.entries(AXES)) {
    for (const [zoom, distance] of Object.entries(DISTANCES)) {
      const h = makeHarness({ axis, distance })
      const from = h.grabPoint()
      h.fire('pointerdown', h.screenOf(from))
      const seen = []
      for (let i = 1; i <= 10; i += 1) {
        const to = from.clone().addScaledVector(h.entry.direction, 0.002 * i)
        h.fire('pointermove', h.screenOf(to))
        seen.push(h.entry.valueMm)
      }
      h.fire('pointerup', h.screenOf(from))
      for (let i = 1; i < seen.length; i += 1) {
        assert.ok(
          seen[i] > seen[i - 1],
          `${label} @ ${zoom} 第 ${i} 步非单调: ${seen.map((v) => v.toFixed(1)).join(' -> ')}`,
        )
      }
    }
  }
})

test('俯视 5Z 时拖动方向不随缩放翻转(用户报的 #1 原形)', () => {
  // 复现姿态: 俯视上样工位看孔板/针 —— 视线与竖直的 5Z 轴夹角小.
  // 修复前实测: 22.2/4.23/1.0/0.5m 给 +20mm, 0.3m 与 0.222m 翻成 −27.1/−26.1mm.
  for (const polarDeg of [30, 20, 12, 10]) {
    const got = Object.entries(DISTANCES).concat([['mid', 1.0], ['sub', 0.5], ['tight', 0.3]])
      .map(([zoom, distance]) => ({
        zoom,
        mm: dragAlongAxis(makeHarness({ axis: [0, 1, 0], distance, polarDeg }), 0.02),
      }))
    for (const { zoom, mm } of got) {
      assert.ok(
        Math.abs(mm - 20) <= TOL_MM,
        `俯视 ${polarDeg}° @ ${zoom}: 期望 +20mm, 实得 ${mm.toFixed(2)}mm` +
          `（全档: ${got.map((g) => `${g.zoom}=${g.mm.toFixed(1)}`).join(', ')}）`,
      )
    }
  }
})

test('视角与轴近平行时拒动并回报 blocked, 而不是静默乱走', () => {
  const seen = []
  const h = makeHarness({ axis: [0, 1, 0], distance: DISTANCES.iso, polarDeg: 2 })
  h.controller.onDrag = (s) => seen.push(s)
  const from = h.grabPoint()
  h.fire('pointerdown', h.screenOf(from))
  h.fire('pointermove', { clientX: CANVAS.width * 0.5, clientY: CANVAS.height * 0.2 })
  h.fire('pointerup', {})
  assert.equal(h.entry.valueMm, 0, `近平行姿态本不该动, 实得 ${h.entry.valueMm}mm`)
  assert.ok(seen.some((s) => s && s.blocked === true), 'onDrag 必须回报 blocked 供 HUD 提示')
})

test('正视轴线时不得静默乱动(退化姿态必须可预测)', () => {
  // 相机沿轴线俯视 —— 轴在屏幕上投影成一点, 此时任何拖拽解都是病态的.
  // 要求: 要么不动, 要么小幅动; 绝不允许把轴甩出成百上千毫米.
  const axisNodeDir = new THREE.Vector3(0, 1, 0)
  const h = makeHarness({ axis: [0, 1, 0], distance: DISTANCES.iso })
  h.camera.position.set(0, DISTANCES.iso, 0)
  h.camera.lookAt(0, 0, 0)
  h.camera.updateMatrixWorld(true)
  const from = h.grabPoint()
  h.fire('pointerdown', h.screenOf(from))
  h.fire('pointermove', { clientX: CANVAS.width * 0.5, clientY: CANVAS.height * 0.2 })
  h.fire('pointerup', { clientX: CANVAS.width * 0.5, clientY: CANVAS.height * 0.2 })
  assert.ok(
    Number.isFinite(h.entry.valueMm) && Math.abs(h.entry.valueMm) < 200,
    `正视轴线时被甩到 ${h.entry.valueMm}mm (轴向 ${axisNodeDir.toArray()})`,
  )
})
