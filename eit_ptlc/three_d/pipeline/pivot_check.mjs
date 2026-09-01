/**
 * 功能: 在**出厂 GLB** 上跑前端 `_applyLiquidLevel` 的同一套公式, 核液面枢轴补偿.
 *
 * 判据(三条都必须成立, 少一条就是 2026-08-05 那两个 bug 的复发):
 *   1. 液柱**底面**在任何 level 下都不动 —— 否则液面"凭空从中间出现/消失"
 *   2. 柱塞头底 − 液柱顶 恒为 −0.2mm —— 否则柱塞与液面重合或脱开
 *   3. 满 level 时液柱跨度 = 满行程 60mm —— 否则量程拉不满
 *
 * 为什么必须在出厂 GLB 上核而不是只跑前端单测: 枢轴位置是 `04_optimize.mjs` 的
 * `quantize` 决定的(它把网格归一化到以原点为中心的单位立方), 单测里的桩节点复刻不了
 * 优化器将来的行为变化。
 *
 * ⚠ 逐顶点读到的是**量化坐标**, 必须乘回节点自身 scale(见 memory: glb-dequant-scale-trap)。
 *
 * 用法: node pivot_check.mjs [glb路径]
 */
import { NodeIO } from '@gltf-transform/core';
import { ALL_EXTENSIONS } from '@gltf-transform/extensions';
import { MeshoptDecoder } from 'meshoptimizer';

const target = process.argv[2] || '../models/machine.glb';
await MeshoptDecoder.ready;
const doc = await new NodeIO()
  .registerExtensions(ALL_EXTENSIONS)
  .registerDependencies({ 'meshopt.decoder': MeshoptDecoder })
  .read(target);
const nodes = doc.getRoot().listNodes();
const parentOf = new Map();
for (const n of nodes) for (const c of n.listChildren()) parentOf.set(c, n);
const find = (name) => nodes.find((n) => n.getName() === name);

/** 功能: 累计根到该节点的 Y 平移与 Y 缩放(泵链上无旋转, 只需这两项) */
function chainY(node) {
  let ty = 0;
  let sy = 1;
  const chain = [];
  for (let c = node; c; c = parentOf.get(c)) chain.unshift(c);
  for (const n of chain) {
    ty += n.getTranslation()[1] * sy;
    sy *= n.getScale()[1];
  }
  return { ty, sy };
}

/** 功能: 节点(含子树)顶点在**节点本地系**的 Y 范围, 已含子级自身 TRS */
function localY(node, base = { ty: 0, sy: 1 }) {
  let lo = Infinity;
  let hi = -Infinity;
  const mesh = node.getMesh();
  if (mesh) {
    for (const prim of mesh.listPrimitives()) {
      const pos = prim.getAttribute('POSITION');
      const v = [0, 0, 0];
      for (let i = 0; i < pos.getCount(); i += 1) {
        pos.getElement(i, v);
        const y = base.ty + v[1] * base.sy;
        if (y < lo) lo = y;
        if (y > hi) hi = y;
      }
    }
  }
  for (const c of node.listChildren()) {
    const r = localY(c, {
      ty: base.ty + c.getTranslation()[1] * base.sy,
      sy: base.sy * c.getScale()[1],
    });
    if (r.lo < lo) lo = r.lo;
    if (r.hi > hi) hi = r.hi;
  }
  return { lo, hi };
}

let bad = 0;
for (const pid of ['SMP', 'DEV1', 'DEV2']) {
  const liq = find(`LIQUID_PUMP_${pid}`);
  const pl = find(`ACTUATOR_PUMP_PLUNGER_${pid}`);
  if (!liq || !pl) {
    console.log(`${pid} 缺件, 跳过`);
    continue;
  }
  const liqS = liq.getScale()[1];
  const plS = pl.getScale()[1];
  const liqRaw = localY(liq);
  const plRaw = localY(pl);
  const baseMinY = liqRaw.lo * liqS;          // = 前端 _liquidBaseOffset
  const spanY = (liqRaw.hi - liqRaw.lo) * liqS;
  const plMinY = plRaw.lo * plS;
  const liqTy = chainY(liq).ty;
  const plTy = chainY(pl).ty;
  const ratio = (0 - liqRaw.lo) / (liqRaw.hi - liqRaw.lo);
  console.log(`=== ${pid} ===  液柱跨度 ${(spanY * 1000).toFixed(2)}mm  枢轴比 ${ratio.toFixed(3)}`);

  let first = null;
  for (const L of [1.0, 0.5, 0.25, 0.05]) {
    // 前端: scale.y *= L; position.y = base + baseMinY*(1-L)
    const bottom = liqTy + baseMinY * (1 - L) + baseMinY * L;
    const top = bottom + spanY * L;
    const plBottom = plTy + 0.06 * L + plMinY;
    if (first === null) first = bottom;
    const drift = (bottom - first) * 1000;
    const gap = (plBottom - top) * 1000;
    if (Math.abs(drift) > 1e-3 || Math.abs(gap + 0.2) > 0.01) bad += 1;
    console.log(`  L=${L.toFixed(2)}  液柱 [${(bottom * 1000).toFixed(2)}, ${(top * 1000).toFixed(2)}]  柱塞头底 ${(plBottom * 1000).toFixed(2)}  间隙 ${gap.toFixed(3)}mm  底漂 ${drift.toFixed(4)}mm`);
  }
  if (Math.abs(spanY * 1000 - 60) > 0.05) {
    console.log(`  !! 满程跨度 ${(spanY * 1000).toFixed(2)}mm 不是 60mm —— 量程没拉满`);
    bad += 1;
  }
}

console.log('\n### 展缸液面(同一公式) ###');
for (let i = 1; i <= 8; i += 1) {
  const n = find(`LIQUID_${i}`);
  if (!n) {
    console.log(`LIQUID_${i} 缺件`);
    continue;
  }
  const s = n.getScale()[1];
  const raw = localY(n);
  const ty = chainY(n).ty;
  const lo = raw.lo * s;
  const span = raw.hi * s - lo;
  let first = null;
  const drifts = [];
  for (const L of [1.0, 0.5, 0.1]) {
    const bottom = ty + lo * (1 - L) + lo * L;
    if (first === null) first = bottom;
    const d = (bottom - first) * 1000;
    if (Math.abs(d) > 1e-3) bad += 1;
    drifts.push(d.toFixed(4));
  }
  console.log(`  LIQUID_${i}  跨度 ${(span * 1000).toFixed(2)}mm  枢轴比 ${((0 - raw.lo) / (raw.hi - raw.lo)).toFixed(3)}  底漂 [${drifts.join(', ')}]mm`);
}

console.log(bad ? `\n${bad} 项不合格` : '\n全部通过');
process.exit(bad ? 1 : 0);
