/**
 * 功能: GLB 优化压缩 —— 去重、剪枝、焊接、简化、合并、量化、meshopt 压缩.
 *
 * 为什么用 gltf-transform 而不是 gltfpack:
 *   gltfpack 更快, 但默认会重命名/折叠节点; 而本项目的 device-manifest 靠节点名与
 *   Blender 侧约定的层级路径来绑定实时数据, 节点名一旦被改动整条绑定链就断了.
 *   gltf-transform 可编程、保名, 并且能按对象排除特定节点不参与合并.
 *
 * 用法:
 *   node 04_optimize.mjs --input work/machine.clean.glb --output models/machine.glb
 *   node 04_optimize.mjs --simplify 0.6          # 更激进的简化(保留 60% 顶点)
 *   node 04_optimize.mjs --no-join               # 保留全部节点结构(M1 之后使用)
 */

import fs from 'node:fs'
import path from 'node:path'
import process from 'node:process'

import { NodeIO, PropertyType } from '@gltf-transform/core'
import { ALL_EXTENSIONS } from '@gltf-transform/extensions'
import { dedup, join, prune, quantize, simplify, weld } from '@gltf-transform/functions'
import { MeshoptEncoder, MeshoptSimplifier } from 'meshoptimizer'

/**
 * 功能: 解析命令行参数.
 * @returns {object} 参数对象
 */
function parseArgs() {
  const args = process.argv.slice(2)
  /** @type {Record<string, string|boolean>} */
  const parsed = {}
  for (let i = 0; i < args.length; i += 1) {
    const key = args[i]
    if (!key.startsWith('--')) continue
    const name = key.slice(2)
    const next = args[i + 1]
    if (next && !next.startsWith('--')) {
      parsed[name] = next
      i += 1
    } else {
      parsed[name] = true
    }
  }
  return parsed
}

/**
 * 功能: 打印带时间戳的日志.
 * @param {string} message 日志内容
 * @returns {void}
 */
function log(message) {
  const now = new Date().toTimeString().slice(0, 8)
  console.log(`[${now}] ${message}`)
}

/**
 * 功能: 统计一个 glTF 文档的规模指标.
 * @param {import('@gltf-transform/core').Document} document 文档
 * @returns {{nodes: number, meshes: number, primitives: number, triangles: number, materials: number}}
 */
function documentStats(document) {
  const root = document.getRoot()
  let primitives = 0
  let triangles = 0

  for (const mesh of root.listMeshes()) {
    for (const primitive of mesh.listPrimitives()) {
      primitives += 1
      const indices = primitive.getIndices()
      const position = primitive.getAttribute('POSITION')
      const count = indices ? indices.getCount() : position ? position.getCount() : 0
      triangles += Math.floor(count / 3)
    }
  }

  return {
    nodes: root.listNodes().length,
    meshes: root.listMeshes().length,
    primitives,
    triangles,
    materials: root.listMaterials().length,
  }
}

/**
 * 功能: 优化主流程.
 * @returns {Promise<void>}
 */
async function main() {
  const args = parseArgs()
  const root = path.resolve(path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1')), '..')

  const input = path.resolve(String(args.input || path.join(root, 'work', 'machine.clean.glb')))
  const output = path.resolve(String(args.output || path.join(root, 'models', 'machine.glb')))
  // 默认 0.70(而非 0.75): SolidWorks 原生 glTF 的网格比走 STEP + OCCT 的更密
  // (整机 461 万 vs 377 万三角形), 0.75 会让最终结果卡在 315 万、超出 300 万的预算门禁.
  // 实测 0.70 收到 294 万, 是刚好达标的最小改动.
  const simplifyRatio = args.simplify === undefined ? 0.70 : Number(args.simplify)
  const simplifyError = args.error === undefined ? 0.0015 : Number(args.error)
  const doJoin = !args['no-join']

  if (!fs.existsSync(input)) {
    console.error(`错误: 输入文件不存在: ${input}\n请先运行 03_clean_model.py`)
    process.exit(1)
  }
  fs.mkdirSync(path.dirname(output), { recursive: true })

  // meshoptimizer 的 wasm 模块需要先就绪
  await MeshoptSimplifier.ready
  await MeshoptEncoder.ready

  // Draco 解码器: SolidWorks 原生 glTF 导出是 Draco 压缩的, 不注册这个依赖
  // 连读都读不进来(报 "Cannot read properties of undefined (reading 'DT_FLOAT32')").
  // 前端只装了 MeshoptDecoder, 所以原生产物必须在这里转成 meshopt.
  const draco3d = await import('draco3d')
  const io = new NodeIO().registerExtensions(ALL_EXTENSIONS).registerDependencies({
    'meshopt.encoder': MeshoptEncoder,
    'draco3d.decoder': await draco3d.createDecoderModule(),
  })

  log(`读取: ${input} (${(fs.statSync(input).size / 1024 / 1024).toFixed(1)} MB)`)
  const document = await io.read(input)

  // 读进来时 Draco 已被解开, 但扩展对象还挂在文档上, 写出时会要求 draco3d.encoder.
  // 我们统一改用 meshopt(前端只装了 MeshoptDecoder), 所以直接把 Draco 扩展卸掉.
  for (const extension of document.getRoot().listExtensionsUsed()) {
    if (extension.extensionName === 'KHR_draco_mesh_compression') {
      extension.dispose()
      log('已卸载 KHR_draco_mesh_compression(改用 meshopt)')
    }
  }

  const before = documentStats(document)
  log(
    `原始: 节点 ${before.nodes} / 网格 ${before.meshes} / 图元 ${before.primitives} / ` +
      `三角形 ${before.triangles.toLocaleString()} / 材质 ${before.materials}`,
  )

  // 转码模式: 只做"换一种压缩", 不动几何也不动层级.
  // 装配工作台加载的是**未清理的原始模型**, 用户要在上面点选零件决定删留 ——
  // 简化会改几何、join 会合并对象、prune 会删掉空节点, 都会让点选失去意义.
  // 但 SolidWorks 原生导出是 Draco 压缩的, 而前端只装了 MeshoptDecoder,
  // 所以仍需过一道 gltf-transform 把它转成 meshopt.
  if (args.passthrough) {
    log('转码模式: 仅 Draco -> meshopt, 不做简化/合并/删减')
    const { meshopt: meshoptOnly } = await import('@gltf-transform/functions')
    const startedAt = Date.now()
    await document.transform(meshoptOnly({ encoder: MeshoptEncoder }))
    await io.write(output, document)
    const after = documentStats(document)
    log(
      `转码后: 节点 ${after.nodes} / 网格 ${after.meshes} / 图元 ${after.primitives} / ` +
        `三角形 ${after.triangles.toLocaleString()} / 材质 ${after.materials}`,
    )
    log(
      `完成: ${output} (${(fs.statSync(output).size / 1024 / 1024).toFixed(2)} MB, ` +
        `耗时 ${((Date.now() - startedAt) / 1000).toFixed(1)}s)`,
    )
    return
  }

  const transforms = [
    // 合并完全相同的访问器与网格, CAD 模型里同型号零件重复度极高.
    //
    // **绝不能去重材质**: 材质台的"拆出为独立零件"(MAT_SOLO_*)与材质组
    // (MAT_GROUP_*)靠的就是"名字唯一"来获得独立可寻址性, 而它们的参数在拆出
    // 那一刻与所属材质类**完全相同** —— 默认的 dedup 会把它们判为重复合并掉,
    // 名字被折叠回类名. 后果极隐蔽: 几何确实独立了(节点还在), 但材质仍挂在共享
    // 类上, 用户改那个类时被拆出的零件跟着一起变色, 看起来像"拆出根本没生效".
    // 材质是几百字节的 JSON, 不去重对体积与绘制调用均无实质影响.
    dedup({
      propertyTypes: [
        PropertyType.ACCESSOR,
        PropertyType.MESH,
        PropertyType.TEXTURE,
        PropertyType.SKIN,
      ],
    }),
    // 删除没有被任何节点引用的资源.
    // keepLeaves: 无子级的空节点默认会被剪掉, 但 TOOL_MOUNT(法兰上的工具挂点,
    // 换夹爪 attach 的父节点)恰是这样的叶子空节点 —— 剪掉它动画引擎就没地方挂工具了.
    prune({ keepLeaves: true }),
    // 焊接**逐位完全相同**的顶点(建索引, 省体积 + 提升顶点缓存命中).
    // 注意别再传 tolerance: gltf-transform 自 2024-04 起删掉了按容差的有损焊接
    // (v4 的 WeldOptions 只剩 overwrite), 传了会被 assignDefaults 原样带过去然后
    // 永不读取 —— 看着像"按 0.1mm 合并", 实际一个近邻顶点都没合. 若将来真要靠
    // 容差把网格焊连通再简化, 正确落点是 Blender 侧的 bmesh.ops.remove_doubles.
    weld(),
  ]

  if (simplifyRatio < 1) {
    transforms.push(
      simplify({ simplifier: MeshoptSimplifier, ratio: simplifyRatio, error: simplifyError }),
    )
  }

  if (doJoin) {
    // 把共享材质且无独立变换的网格合并, 直接降低绘制调用数.
    // M1 之后需要独立驱动的运动件已在 Blender 侧被单独分组, 不会被误合并.
    // cleanup: false —— join 内部自带的 prune **不带 keepLeaves**, 会把 TOOL_MOUNT
    // (法兰上的工具挂点, 叶子空节点)剪掉; 关掉它, 由链尾统一补一次带 keepLeaves 的 prune.
    transforms.push(join({ keepNamed: true, cleanup: false }))
    transforms.push(prune({ keepLeaves: true }))
  }

  transforms.push(
    // 顶点属性量化: 位置用 14 位整数即可, 显著缩小体积
    quantize({ quantizePosition: 14, quantizeNormal: 10, quantizeTexcoord: 12 }),
  )

  log(
    `变换链: dedup -> prune -> weld` +
      (simplifyRatio < 1 ? ` -> simplify(${simplifyRatio})` : '') +
      (doJoin ? ' -> join' : '') +
      ' -> quantize -> meshopt',
  )

  const started = Date.now()
  await document.transform(...transforms)

  // meshopt 压缩必须最后做, 且需要在 quantize 之后
  const { meshopt } = await import('@gltf-transform/functions')
  await document.transform(meshopt({ encoder: MeshoptEncoder, level: 'high' }))

  await io.write(output, document)
  const elapsed = ((Date.now() - started) / 1000).toFixed(1)

  const after = documentStats(document)
  const outputMb = fs.statSync(output).size / 1024 / 1024

  log(
    `优化后: 节点 ${after.nodes} / 网格 ${after.meshes} / 图元 ${after.primitives} / ` +
      `三角形 ${after.triangles.toLocaleString()} / 材质 ${after.materials}`,
  )
  log(`完成: ${output} (${outputMb.toFixed(2)} MB, 耗时 ${elapsed}s)`)

  const report = {
    input,
    output,
    output_mb: Number(outputMb.toFixed(2)),
    simplify_ratio: simplifyRatio,
    joined: doJoin,
    elapsed_s: Number(elapsed),
    before,
    after,
  }
  const reportPath = path.join(root, 'work', '04_optimize.report.json')
  fs.writeFileSync(reportPath, JSON.stringify(report, null, 2), 'utf-8')
  log(`报告已写入: ${reportPath}`)
}

main().catch((error) => {
  console.error('优化失败:', error)
  process.exit(1)
})
