/**
 * 功能: 核出厂 GLB 里"液柱 vs 柱塞组"的径向间隙, 判有无同轴共面.
 *
 * 为什么要单独量: 柱塞头与液柱是同轴等径圆柱时, 两者侧壁**完全共面** —— 深度排序
 * 每帧翻面, 画面上就是一圈上下贯穿的竖条纹(2026-08-05 用户截图里筒内那些白道子).
 * 这类缺陷"体积/包围盒/共面对检测"都抓不到: 它们各自都是合法闭合体, 只是半径撞了。
 *
 * 顶点必须乘回 node.scale —— 04 的 quantizePosition 把几何归一化到单位立方后
 * 把尺度推到了 TRS 上, 直接读顶点得到的是量化坐标(见 memory: glb-dequant-scale-trap)。
 *
 * 用法: node radial_check.mjs [glb路径]
 */
import { NodeIO } from '@gltf-transform/core';
import { ALL_EXTENSIONS } from '@gltf-transform/extensions';
import { MeshoptDecoder } from 'meshoptimizer';

const target = process.argv[2] || '../models/machine.glb';
// 出厂 GLB 是 meshopt 压缩的(04 步统一转的, 前端只装 Decoder), 不挂解码器读不出顶点
await MeshoptDecoder.ready;
const doc = await new NodeIO()
  .registerExtensions(ALL_EXTENSIONS)
  .registerDependencies({ 'meshopt.decoder': MeshoptDecoder })
  .read(target);
const root = doc.getRoot();
const find = (name) => root.listNodes().find((n) => n.getName() === name);

/**
 * 功能: 取节点(含子树)所有顶点在轴线周围的最大半径, 单位 mm.
 *
 * 缩放必须**沿链累乘**: 可动件是组节点(自身 scale=1), 量化尺度落在各子网格上,
 * 只取组节点的 scale 会把 0.04 当成 1, 半径直接错 25 倍。
 * 半径还要绕各自的轴心算 —— 子件在组内有横向偏移(滑车 z=-13.6mm), 拿组原点当轴心
 * 会把偏移误算进半径。
 */
function maxRadiusMm(node) {
  let r = 0;
  const walk = (n, scale) => {
    const s = n.getScale().map((v, i) => v * scale[i]);
    const mesh = n.getMesh();
    if (mesh) {
      // 先求本网格自己的 XZ 轴心, 再量绕它的半径
      let x0 = Infinity, x1 = -Infinity, z0 = Infinity, z1 = -Infinity;
      const pts = [];
      for (const prim of mesh.listPrimitives()) {
        const pos = prim.getAttribute('POSITION');
        const v = [0, 0, 0];
        for (let i = 0; i < pos.getCount(); i += 1) {
          pos.getElement(i, v);
          const x = v[0] * s[0], z = v[2] * s[2];
          pts.push([x, z]);
          if (x < x0) x0 = x; if (x > x1) x1 = x;
          if (z < z0) z0 = z; if (z > z1) z1 = z;
        }
      }
      const cx = (x0 + x1) / 2, cz = (z0 + z1) / 2;
      for (const [x, z] of pts) r = Math.max(r, Math.hypot(x - cx, z - cz));
    }
    n.listChildren().forEach((c) => walk(c, s));
  };
  walk(node, [1, 1, 1]);
  return r * 1000;
}

let bad = 0;
for (const id of ['SMP', 'DEV1', 'DEV2']) {
  const liquid = find(`LIQUID_PUMP_${id}`);
  const group = find(`ACTUATOR_PUMP_PLUNGER_${id}`);
  if (!liquid || !group) {
    console.log(`${id}  缺件, 跳过`);
    continue;
  }
  const rl = maxRadiusMm(liquid);
  // 只跟**柱塞头**比: 滑车在窗腔里(r≈19), 拿它比会把真正的共面掩盖掉
  const head = group.listChildren().find((c) => c.getName().includes('柱塞'));
  if (!head) {
    console.log(`${id}  柱塞头缺件, 跳过`);
    continue;
  }
  const rp = maxRadiusMm(head);
  const gap = rp - rl;
  // 判据 0.15mm: 小于它两个同轴圆柱的侧壁在任何视距下都会互相穿插闪烁
  const risky = Math.abs(gap) < 0.15;
  if (risky) bad += 1;
  console.log(`${id}  液柱 r=${rl.toFixed(2)}mm  柱塞头 r=${rp.toFixed(2)}mm  径向差=${gap.toFixed(2)}mm  ${risky ? '共面风险' : '通过'}`);
}
console.log(bad ? `\n${bad} 台有共面风险` : '\n全部通过');
process.exit(bad ? 1 : 0);
