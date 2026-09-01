# WebGPU 节点管线探底 · 本机实测记录 (2026-08-03)

> 目的: 为"三维模块要不要从 WebGL(pmndrs/postprocessing) 迁到 WebGPU(TSL 节点管线)"
> 这个决策提供实测依据。本文只记事实与当场归因, 不下最终结论 ——
> **决定性的那一条(现场工控机上 WebGPU 可不可用)本机测不了, 见文末"待补"。**

复现: `npm run dev` 后跑 `three_d/tools/visual_validation/spike_webgpu.py`。
spike 代码在 `web/spike-webgpu.html` + `web/src/three-d-webgpu-spike/`,
是一次性调研件, 与现役 `twin/scene/*` 零耦合, 结论落定后可整个删除。

测试环境: RTX 4090 / 3840×2160 / Windows 11 / Chromium(有头) / three 0.185.1。
模型: `models/machine.official-cr5.glb`(与实时页同一份)。视口 1600×1000, DPR 2。

---

## 1. WebGPU 后端可用 ✔

`WebGPURenderer` 在本机取到真 WebGPU 后端(`backend.isWebGPUBackend === true`),
整机模型渲染正常, 控制台 0 错误。

⚠ **无头 Chromium 不暴露 `navigator.gpu`**(加 `--enable-unsafe-webgpu` 也没用),
所以 spike 脚本必须 `headless=False`。无头下只会测到 WebGL 回退档 —— 那就把结论测反了。

## 2. 量化/meshopt 几何完全兼容 ✔ (本次最重要的一条)

这是迁移路线上**唯一可能一票否决的资产层风险**, 实测排除:

| 指标 | 实测 |
|---|---|
| 三角形 | 2,934,998 |
| 网格 | 767 |
| `InterleavedBufferAttribute` 属性数 | **1534** |
| `normalized` 整型属性数 | **1534** |

`EXT_meshopt_compression` + `KHR_mesh_quantization` 的产物(交错缓冲 + Int16/Int8
归一化)在 `WebGPURenderer` 下**直接渲染正确, 无需任何预处理**。

> 对照: 计划里 Phase 4 的路径追踪走 `three-gpu-pathtracer` 时**必须**先去交错 + 反量化
> (`StaticGeometryGenerator` 在类型不一致时抛空消息 Error)。两条路对同一批几何的
> 要求完全不同, 别把 spike 的这条结论套到路径追踪上。

## 3. 基础渲染路径: WebGPU 比 WebGL 快约 30% ✔

脱开 vsync 连续 `await renderer.renderAsync()` 60 帧测吞吐(setAnimationLoop 被 vsync
钉在 16.7 ms, 测不出余量):

| 后端 | 帧耗时 | 说明 |
|---|---|---|
| WebGPU | **1.53 ms** | 同一份场景/灯光/阴影 |
| WebGL(`forceWebGL: true`) | **2.24 ms** | 同一份代码走回退后端 |

同一份代码传 `forceWebGL: true` 渲染结果与 WebGPU **肉眼一致**(亮度统计 58.40 vs 58.41),
证实"不需要维护两套渲染路径"这条判断 —— 至少在**基础路径**上成立。

## 4. TSL 后期节点**不是拿来即用** ✘ (与迁移前的预期不符)

逐级累加测(`?fx=off|gtao|ssgi|ssr|traa`), 七档**全部 0 错误、0 警告**, 但输出:

| 档位 | 结果 | 现象 |
|---|---|---|
| off | ✔ 正确 | 基线 |
| +GTAO | ✘ 错 | **整机变成一片纯红** —— AO 是单通道 R 缓冲, 被当 RGBA 乘回 beauty |
| +SSGI | ✘ 错 | 全屏泛光, 非黑像素 99.8%(正常应是 27%) |
| +SSR | ✘ 黑屏 | 无报错无警告 |
| +TRAA | ✘ 黑屏 | 同上 |

**关键教训: 这些节点接错时不报错, 只是静默出错图。** 与硬约束 33/35 是同一类失败模式。

已知的两个接线坑(已在 spike 里修掉, 记下来免得再踩):
- `ssr()` 第四参是 **options 对象**且 `camera` 必须显式传, 不传报
  `THREE.SSRNode: No camera found`; `metalness`/`roughness` 走
  `options.metalnessNode/roughnessNode`, 不是位置参数。
- `TRAA` 需要 MRT 里有 `velocity`, 漏了拿到空节点。

剩下的(AO 单通道消费方式、SSGI 参数、SSR/TRAA 黑屏)**没查到根因**。
判断: 不是"WebGPU 做不到", 而是"把这四个节点接对是实打实的工作量" ——
这一条直接修正了迁移前"in-tree 维护所以拿来就能用"的乐观预期。

## 5. 没测到的

- **后期链的帧耗时。** `PostProcessing.renderAsync()` 实测是空转(读数 0.02 ms/帧
  显然不可信), 同步 `render()` 又是 fire-and-forget, 墙钟测不到 GPU 时间。
  要拿这个数得把 GPU timestamp 接通(`renderer.trackTimestamp` +
  `resolveTimestampsAsync`, 本次未跑通)。**所以"开满效果之后还剩多少余量"仍是未知数。**
- **观感对比。** 四个节点都没接对, 谈不上与现役 high 档并排目检。

---

## 待补: 决定性的那一条

**现场工控机上 WebGPU 可不可用 —— 本机测不了, 必须到现场机上看。**

在现场机(或同型号同驱动的机器)开 `chrome://gpu`, 记录:

1. **WebGPU 一行是否为 "Hardware accelerated"**(不是 Disabled/Software only/Blocklisted)
2. 浏览器名与版本(WebGPU 需 Chrome/Edge 113+)
3. GPU 型号与驱动版本; `WebGL2` 一行是否也是 Hardware accelerated
4. `chrome://flags` 里 WebGPU 相关项是否被组策略锁定(工控机常有)
5. 顺带记 `EXT_disjoint_timer_query_webgl2` 是否可用 —— 这条与迁移无关,
   但决定计划 Phase 3 首屏定档的可靠性(没有它微基准会拟合出 slope≈0)

若该机 WebGPU 不可用 / 被策略锁, 迁移就是**付全部重写成本却恰好拿不到理由**
(SSGI/TRAA 依赖 compute 与 MRT, 回退档下拿不到), 应直接走计划里的分叉 B。
