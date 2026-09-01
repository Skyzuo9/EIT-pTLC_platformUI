/**
 * 功能: 把 SolidWorks 单独重导的高镶嵌零件网格, 换进 03 的产物 machine.full.glb.
 *
 * 治的是什么: 整机 glTF 按**装配体文档**的图像品质镶嵌, 圆柱面普遍只有 30~40 段
 * (Ø50 的 `管路润洗收集瓶-1` 实测 10.27°/面). 近景下一个刻面约 32 屏幕像素, 平滑着色
 * 也压不住, 读起来就是"圆柱上一圈没来由的竖向明暗带". 把该零件文档的图像品质单独拉高
 * 后重导, 同一圆柱到 1.13°/面. 替换表见 hires_overrides.json.
 *
 * 为什么注入点在 03 与 04 之间(而不是直接改 models/machine.glb):
 *   - machine.full.glb 里装配变换已经烘进**节点**, 网格仍是零件自身的局部坐标,
 *     且实测与单零件重导的局部坐标系逐点对齐(bbox 差 0.05mm, 节点 scale=1)
 *     —— 所以直接换网格数据即可, 不需要任何配准数学;
 *   - 它是未压缩 float, 改起来没有量化/meshopt 的包袱;
 *   - 换完由 04 正常做减面/量化/meshopt, 产物与平时同构;
 *   - 直接改 models/machine.glb 会被下一次重建冲掉。
 *
 * 硬校验: 换完的包围盒必须与原件一致(默认 0.5mm)。尺寸是唯一独立于示教点的校验手段,
 * 不许被静默改掉 —— 对不上就**非零退出**, 绝不"凑合着换上去".
 *
 * 用法:
 *   node 06_hires_swap.mjs                                   # 就地改写 machine.full.glb
 *   node 06_hires_swap.mjs --input ../work/a.glb --output ../work/b.glb
 *   node 06_hires_swap.mjs --dry-run                         # 只校验与报数, 不写文件
 */
import fs from 'node:fs'
import path from 'node:path'
import process from 'node:process'

import { NodeIO } from '@gltf-transform/core'
import { ALL_EXTENSIONS } from '@gltf-transform/extensions'
import { simplifyPrimitive, weldPrimitive } from '@gltf-transform/functions'
import { MeshoptDecoder, MeshoptEncoder, MeshoptSimplifier } from 'meshoptimizer'

/** 功能: 带时间戳打印. 参数: message. 返回值: 无 */
function log(message) {
  const now = new Date().toTimeString().slice(0, 8)
  console.log(`[${now}] ${message}`)
}

/** 功能: 解析 --key value 形式的命令行. 参数: argv. 返回值: 键值对象 */
function parseArgs(argv) {
  const args = {}
  for (let i = 0; i < argv.length; i += 1) {
    if (!argv[i].startsWith('--')) continue
    const key = argv[i].slice(2)
    const next = argv[i + 1]
    if (next === undefined || next.startsWith('--')) args[key] = true
    else { args[key] = next; i += 1 }
  }
  return args
}

/** 功能: 去掉 glTF 同名节点的 .001 后缀. 参数: name. 返回值: 基名 */
const baseName = (name) => String(name || '').replace(/\.\d{3}$/, '')

/** 功能: 取一批 primitive 的局部坐标包围盒(米). 参数: primitives. 返回值: {min,max} */
function localBBox(primitives) {
  const min = [Infinity, Infinity, Infinity]
  const max = [-Infinity, -Infinity, -Infinity]
  const p = [0, 0, 0]
  for (const prim of primitives) {
    const pos = prim.getAttribute('POSITION')
    if (!pos) continue
    for (let i = 0; i < pos.getCount(); i += 1) {
      pos.getElement(i, p)
      for (let k = 0; k < 3; k += 1) {
        if (p[k] < min[k]) min[k] = p[k]
        if (p[k] > max[k]) max[k] = p[k]
      }
    }
  }
  return { min, max }
}

/** 功能: 数三角形. 参数: primitives. 返回值: 三角形数 */
function triangles(primitives) {
  let total = 0
  for (const prim of primitives) {
    const indices = prim.getIndices()
    if (indices) total += indices.getCount() / 3
    else total += (prim.getAttribute('POSITION')?.getCount() ?? 0) / 3
  }
  return Math.round(total)
}

async function main() {
  const args = parseArgs(process.argv.slice(2))
  const root = path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1'))

  const configPath = path.resolve(root, String(args.config || 'hires_overrides.json'))
  const input = path.resolve(root, String(args.input || '../work/machine.full.glb'))
  const output = path.resolve(root, String(args.output || input))
  const dryRun = Boolean(args['dry-run'])

  if (!fs.existsSync(configPath)) {
    console.error(`错误: 替换表不存在: ${configPath}`)
    process.exit(1)
  }
  const config = JSON.parse(fs.readFileSync(configPath, 'utf-8'))
  const overrides = config.overrides || []
  if (!overrides.length) {
    log('替换表为空, 什么都不做')
    return
  }
  if (!fs.existsSync(input)) {
    console.error(`错误: 输入不存在: ${input}\n请先运行 03_clean_model.py`)
    process.exit(1)
  }

  await MeshoptDecoder.ready
  await MeshoptEncoder.ready
  await MeshoptSimplifier.ready

  // Draco: SolidWorks 原生 glTF 导出是 Draco 压缩的, 不注册解码器连读都读不进来
  const draco3d = await import('draco3d')
  const io = new NodeIO().registerExtensions(ALL_EXTENSIONS).registerDependencies({
    'meshopt.decoder': MeshoptDecoder,
    'meshopt.encoder': MeshoptEncoder,
    'draco3d.decoder': await draco3d.default.createDecoderModule(),
  })

  log(`读取: ${input} (${(fs.statSync(input).size / 1024 / 1024).toFixed(1)} MB)`)
  const doc = await io.read(input)
  const buffer = doc.getRoot().listBuffers()[0]

  const report = { input, output, dryRun, swapped: [] }
  let failed = 0

  for (const rule of overrides) {
    const wanted = baseName(rule.node)
    const targets = doc.getRoot().listNodes().filter(
      (n) => baseName(n.getName()) === wanted && n.getMesh(),
    )
    if (!targets.length) {
      console.error(`错误: 目标节点不存在: ${rule.node}`)
      failed += 1
      continue
    }

    const sourcePath = path.resolve(root, rule.source)
    if (!fs.existsSync(sourcePath)) {
      console.error(`错误: 高精件不存在: ${sourcePath}`)
      failed += 1
      continue
    }
    const src = await io.read(sourcePath)
    const srcPrims = []
    for (const mesh of src.getRoot().listMeshes()) srcPrims.push(...mesh.listPrimitives())
    if (!srcPrims.length) {
      console.error(`错误: 高精件里没有可用图元: ${sourcePath}`)
      failed += 1
      continue
    }

    const before = { bbox: localBBox(targets[0].getMesh().listPrimitives()), tris: 0 }
    before.tris = triangles(targets[0].getMesh().listPrimitives())
    const srcTrisRaw = triangles(srcPrims)

    // 抽稀: 高精件往往过头(1.13°/面), 先收一道, 再交给 04 的一刀切.
    // simplify 要求已焊接的索引网格, 所以先 weld.
    const ratio = Number(rule.simplifyRatio)
    if (Number.isFinite(ratio) && ratio > 0 && ratio < 1) {
      for (const prim of srcPrims) {
        weldPrimitive(prim)
        simplifyPrimitive(prim, {
          simplifier: MeshoptSimplifier,
          ratio,
          error: Number(rule.simplifyError ?? 0.0001),
        })
      }
    }
    const srcTris = triangles(srcPrims)

    // 硬校验: 包围盒必须一致 —— 尺寸是独立于示教点的唯一校验手段, 不许静默改掉
    const after = localBBox(srcPrims)
    const tol = Number(rule.maxBBoxDeltaMm ?? 0.5) / 1000
    const deltas = []
    for (let k = 0; k < 3; k += 1) {
      deltas.push(Math.abs(after.min[k] - before.bbox.min[k]))
      deltas.push(Math.abs(after.max[k] - before.bbox.max[k]))
    }
    const worst = Math.max(...deltas)
    if (worst > tol) {
      console.error(
        `错误: ${rule.node} 包围盒对不上, 最大偏差 ${(worst * 1000).toFixed(3)} mm > 容差 `
        + `${(tol * 1000).toFixed(2)} mm\n`
        + `      原件 [${before.bbox.min.map((v) => (v * 1000).toFixed(2))}] .. `
        + `[${before.bbox.max.map((v) => (v * 1000).toFixed(2))}]\n`
        + `      新件 [${after.min.map((v) => (v * 1000).toFixed(2))}] .. `
        + `[${after.max.map((v) => (v * 1000).toFixed(2))}]`,
      )
      failed += 1
      continue
    }

    // 把源图元的数组搬进目标文档(跨 Document 不能直接引用对象, 只能重建 accessor).
    // 材质一律沿用**目标**的 —— 高精件带的是 SolidWorks 原始外观, 而整机的材质是
    // 管线按 materials.yaml 赋过的, 换掉会让这个零件脱离材质体系(材质台也就管不到它).
    for (const node of targets) {
      const targetMesh = node.getMesh()
      const material = targetMesh.listPrimitives()[0]?.getMaterial() ?? null
      for (const old of targetMesh.listPrimitives()) {
        targetMesh.removePrimitive(old)
        old.dispose()
      }
      for (const prim of srcPrims) {
        const fresh = doc.createPrimitive().setMaterial(material)
        for (const semantic of prim.listSemantics()) {
          const attr = prim.getAttribute(semantic)
          fresh.setAttribute(semantic, doc.createAccessor()
            .setArray(attr.getArray().slice())
            .setType(attr.getType())
            .setNormalized(attr.getNormalized())
            .setBuffer(buffer))
        }
        const indices = prim.getIndices()
        if (indices) {
          fresh.setIndices(doc.createAccessor()
            .setArray(indices.getArray().slice())
            .setType(indices.getType())
            .setBuffer(buffer))
        }
        targetMesh.addPrimitive(fresh)
      }
    }

    log(`替换 ${rule.node} ×${targets.length}: 三角形 ${before.tris.toLocaleString()} -> `
      + `${srcTris.toLocaleString()} (高精原件 ${srcTrisRaw.toLocaleString()}, `
      + `抽稀比 ${Number.isFinite(ratio) ? ratio : 1}); 包围盒最大偏差 `
      + `${(worst * 1000).toFixed(3)} mm`)
    report.swapped.push({
      node: rule.node,
      instances: targets.length,
      trisBefore: before.tris,
      trisAfter: srcTris,
      trisSourceRaw: srcTrisRaw,
      bboxDeltaMm: Number((worst * 1000).toFixed(4)),
    })
  }

  if (failed) {
    console.error(`替换失败 ${failed} 项, 未写出任何文件`)
    process.exit(1)
  }
  if (dryRun) {
    log('--dry-run: 校验通过, 不写文件')
  } else {
    await io.write(output, doc)
    log(`完成: ${output} (${(fs.statSync(output).size / 1024 / 1024).toFixed(1)} MB)`)
  }

  const reportPath = path.resolve(root, '../work/06_hires_swap.report.json')
  fs.mkdirSync(path.dirname(reportPath), { recursive: true })
  fs.writeFileSync(reportPath, JSON.stringify(report, null, 2), 'utf-8')
}

main().catch((err) => {
  console.error(err)
  process.exit(1)
})
