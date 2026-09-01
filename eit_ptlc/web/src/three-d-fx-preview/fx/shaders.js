/**
 * 功能: 沙盒特效共用 GLSL 片段. 集中一处便于对照面板调参与后续搬迁.
 *
 * 约定: 全部发光材质 transparent + depthWrite:false, 颜色乘 uBoost 抬过辉光
 * 亮度阈值(0.35); low 档没有辉光时 additive 本身仍有光感 = 天然降级形态.
 */

/** 通用 passthrough 顶点: 只传 uv */
export const PASS_VERT = /* glsl */ `
varying vec2 vUv;
void main() {
  vUv = uv;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}
`

/**
 * 地面雷达光环: 外细环 + 内细环 + 36 格刻度 + (busy)旋转扫描弧 + 中心径向辉光.
 * uMode: 0=静环  1=旋转扫描弧  2=报警快闪(方波)
 */
export const RING_FRAG = /* glsl */ `
uniform float uTime;
uniform vec3 uColor;
uniform float uOpacity;
uniform float uPulse;   // 呼吸/快闪频率 Hz, 0=不脉动(取 manifest healthStyles.pulse)
uniform float uSpin;    // 扫描弧角速度 rad/s
uniform float uMode;
uniform float uBoost;
varying vec2 vUv;

void main() {
  vec2 p = vUv - 0.5;
  float r = length(p) * 2.0;
  float theta = atan(p.y, p.x);

  float ring = smoothstep(0.020, 0.005, abs(r - 0.92));
  float ring2 = smoothstep(0.014, 0.003, abs(r - 0.70)) * 0.55;
  // 外环上的角向刻度网纹
  float ticks = smoothstep(0.86, 0.99, cos(theta * 36.0)) * smoothstep(0.06, 0.02, abs(r - 0.92)) * 0.5;

  float arc = 0.0;
  if (uMode > 0.5 && uMode < 1.5) {
    float band = smoothstep(0.15, 0.03, abs(r - 0.81));
    float a1 = fract((theta - uTime * uSpin) / 6.2831853);
    float a2 = fract((theta - uTime * uSpin) / 6.2831853 + 0.5);
    arc = (exp(-a1 * 8.0) + exp(-a2 * 8.0) * 0.6) * band;
  }

  // 中心径向辉光压低: additive 叠在白色台面上, 0.3 会糊成一片白
  float glow = exp(-r * 3.0) * 0.16;

  float pulse = 1.0;
  if (uPulse > 0.01) {
    float wave = sin(uTime * 6.2831853 * uPulse);
    // 报警用方波快闪, 呼吸用正弦
    pulse = uMode > 1.5 ? (step(0.0, wave) * 0.85 + 0.15) : (0.72 + 0.28 * wave);
  }

  float alpha = (ring + ring2 + ticks + arc + glow) * uOpacity * pulse;
  alpha *= smoothstep(1.0, 0.97, r);
  gl_FragColor = vec4(uColor * uBoost, alpha);
}
`

/** 全息壳顶点: 法线外推(uInflate 是**模型局部单位**, 换算在 JS 侧做) */
export const SHELL_VERT = /* glsl */ `
uniform float uInflate;
varying vec3 vNormalV;
varying vec3 vViewV;
varying float vWorldY;
void main() {
  vec3 pos = position + normal * uInflate;
  vec4 world = modelMatrix * vec4(pos, 1.0);
  vWorldY = world.y;
  vec4 mv = viewMatrix * world;
  vNormalV = normalMatrix * normal;
  vViewV = -mv.xyz;
  gl_Position = projectionMatrix * mv;
}
`

/** 全息壳片元: Fresnel 边缘光 + 世界 Y 上移扫描亮带 */
export const SHELL_FRAG = /* glsl */ `
uniform vec3 uColor;
uniform float uFresnel;
uniform float uPower;
uniform float uBand;
uniform float uBandY;   // 亮带当前世界高度(米)
uniform float uBandW;   // 亮带半宽(米)
uniform float uOpacity;
varying vec3 vNormalV;
varying vec3 vViewV;
varying float vWorldY;
void main() {
  float f = pow(1.0 - abs(dot(normalize(vNormalV), normalize(vViewV))), uPower);
  float band = smoothstep(uBandW, 0.0, abs(vWorldY - uBandY));
  float alpha = clamp(f * uFresnel + band * uBand, 0.0, 1.5) * uOpacity;
  gl_FragColor = vec4(uColor * (1.0 + band * 1.5), alpha);
}
`

/** 扫描波竖直光幕: 边缘淡出 + 细竖栅纹 */
export const SCAN_SHEET_FRAG = /* glsl */ `
uniform vec3 uColor;
uniform float uOpacity;
uniform float uBoost;
varying vec2 vUv;
void main() {
  float ez = smoothstep(0.0, 0.12, vUv.x) * smoothstep(1.0, 0.88, vUv.x);
  float ey = smoothstep(0.0, 0.05, vUv.y) * smoothstep(1.0, 0.72, vUv.y);
  float stripes = 0.85 + 0.15 * cos(vUv.x * 90.0);
  gl_FragColor = vec4(uColor * uBoost, ez * ey * stripes * uOpacity);
}
`

/** 扫描波地面拖尾: 朝波前(uv.x=1)加亮, 尾部指数衰减 */
export const SCAN_TRAIL_FRAG = /* glsl */ `
uniform vec3 uColor;
uniform float uOpacity;
uniform float uBoost;
varying vec2 vUv;
void main() {
  float ez = smoothstep(0.0, 0.1, vUv.y) * smoothstep(1.0, 0.9, vUv.y);
  float fade = pow(clamp(vUv.x, 0.0, 1.0), 3.0);
  float core = smoothstep(0.94, 1.0, vUv.x) * 2.0;
  gl_FragColor = vec4(uColor * uBoost, (fade * 0.5 + core) * ez * uOpacity);
}
`

/** 任务流光带(TubeGeometry: uv.x 沿管长): 头部揭示 + 亮段行进 */
export const FLOW_FRAG = /* glsl */ `
uniform float uTime;
uniform float uHead;    // 揭示进度 0..1
uniform float uRepeat;
uniform float uSpeed;
uniform float uFade;    // 整体淡出(播完 -> 0)
uniform vec3 uColor;
uniform float uBoost;
varying vec2 vUv;
void main() {
  float reveal = 1.0 - smoothstep(uHead - 0.015, uHead, vUv.x);
  float band = smoothstep(0.45, 0.95, fract(vUv.x * uRepeat - uTime * uSpeed));
  float alpha = (0.22 + 0.78 * band) * reveal * uFade;
  gl_FragColor = vec4(uColor * uBoost, alpha);
}
`
