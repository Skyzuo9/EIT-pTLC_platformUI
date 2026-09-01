# AR 增强显示 · 效果预览沙盒

给 `/3d/live` 数字孪生实时界面预研的"增强现实风格"展示层，页面套**仿正式应用外壳**
(侧栏/顶栏/页签，看起来就是未来产品)：**悬停白色信息卡 + 点击聚焦(每工位定制视角、
周围幽灵化、对象实体+描边) + 点门开关门 + "幽灵整机自上而下渐进实体化+环绕+蓝色
扫描面"开场 + 巡检 + 精编译流程片段播放 + 显示设置**。真机 GLB + 确定性模拟剧本
(或真实流程动画)驱动。

第六轮补丁(2026-08-09, 用户反馈"开门时把手留在原地")：门体 `nodes` 补上骑在门上的
五金 —— 8 只把手直接进 `part_isolate`；16 片合页门叶因 CAD 同名无法直接孤立，新增
`blender_clean.rename_door_hinge_leaves()` 按几何改名后再孤立。见「开关门」节。
第六轮(2026-08-09, 用户反馈"开门方向反了")：门从 4 扇扩到 **8 扇**，铰链边/开向改由
**CAD 合页件 `AKQ41-G-Z-6065` + 把手 `XAD51-A100` 反查**而非推测——订正 `feed`(原挂在
把手边)与 `back`(原往柜内开)，并新增前后长面左半各一对**对开门**(`frontL1/L2`、
`backL1/L2`，把手相邻于中缝，点一扇两扇同开)。管线侧 `固定门板-2/-3/-5/-6` 补进
`part_isolate`(那 4 扇曾被误判为"按图纸不可开")。见「开关门」节。
第四轮(2026-08-06, 用户定夺)：状态圆点整个退役；开场换**幽灵扫场**(整机虚拟态由左
往右逐渐实体化)；聚焦/巡检不再自动取景，改 **stationViews 每工位定制机位**(正面半球、
按包围盒 8 角点精确解距离保证完整入画)；新增 **4 扇可开门**(左端双开侧门×2/前上料门
[钣金框+亚克力窗刚性同转]/后侧门板，点哪扇开哪扇)；页面套仿正式外壳、控制面板改
可最小化卡片；管线侧把小铁片(瓶子检测光电安装板-3)归位 FEEDLIFT、三扇门 part_isolate
分离(备份在 `three_d/work/backup_20260806_round4/`)。
第三轮：悬停白卡(realvirtual 风格)、聚焦实体化(共享幽灵材质换引用)、工位归属重跑
(中转座A→STAGINGA、新 VISION 组)、地轨并入机械臂组。
第二轮：流程片段播放、显示设置(修浅色过曝)、锚点"顶部带加权中心"。

> **本目录 + `web/fx-preview.html` 是预览沙盒，不进生产构建**（vite 只打包 index.html），
> 与 `src/three-d/twin/**` 零耦合（只复用纯叶子模块 `loadModel.js` 与全局样式表）。
> 结论落定后可整体删除，或按文末"阶段B合入路径"把选中效果的内核搬进 twin/。

## 怎么跑

1. 后端 18080 在线（模型与 manifest 走 `/api/3d/assets`，15173 经 vite 代理转发）。
2. `cd eit_ptlc/web && npm run dev`（钉在 127.0.0.1:15173）。
3. 打开：
   - 五态摆拍（主打场景）：<http://127.0.0.1:15173/fx-preview.html?scenario=showcase>
   - 带开场动画：<http://127.0.0.1:15173/fx-preview.html?scenario=showcase&fx=all>
   - 循环任务（动态，含搬运滑座跟随）：<http://127.0.0.1:15173/fx-preview.html?fx=all>

右上"效果预览"卡片：主题/特效/流程播放/场景模拟/显示设置/参数/机位；可用 — 钮最小化
成胶囊。**面板任何改动都会回写地址栏 —— 复制 URL 即可复现当前画面。**

交互：悬停工位看白卡 · 点击工位聚焦(定制视角) · **点门开关门** · Esc 退出 ·
`H` 面板显隐 · `T` 巡检 · `1-9` 按左→右序选工位。

## URL 参数表

| 参数 | 取值 | 默认 | 说明 |
|---|---|---|---|
| `theme` | dark / light | dark | 深色是展示形态，浅色是兼容形态 |
| `fx` | cards,focus,tour,intro / all | cards,focus | 特效启用清单(cards=悬浮信息卡) |
| `scenario` | running / idle / error / showcase | running | 模拟剧本 |
| `quality` | high / low | high | low = 无后期链的降级预览（无辉光/无描边） |
| `speed` | 数字 | 1 | 剧本倍速 |
| `focus` | 工位 id（如 DEVELOP） | - | 载入后自动聚焦 |
| `cam` | iso/front/back/left/right/top/station:<id> | iso | 初始机位 |
| `step` | 剧本步序号 0-9 | - | 跳到剧本第 N 步 |
| `freeze` / `freezetime` | 1 / 秒数 | - | 冻结定格（截图复现的根；门动画走真实时间不受冻结驱动） |
| `intro` | 0/1 | fx 含 intro 时 1 | 开场扫场开关 |
| `panel` | 0/1 | 1 | 控制面板显隐 |
| `clip` / `clipt` | 片段名 / 秒 | - | 载入流程片段(如 flow.sampling_execute)并 seek 定格 |
| `isolate` | ghost / hide / off | ghost | 聚焦/巡检时对周围结构: 幽灵半透明 / 隐藏 / 不处理 |
| `debug` | 0/1 | 0 | 悬浮卡追加"零件"行(显示射中的网格/合并块名, 指认错归零件用) |
| `aa` / `dpr` / `autorotate` | 0/1 / 数字 / 0/1 | 1 / min(dpr,2) / 0 | 抗锯齿 / DPR 上限 / 自动环绕 |
| `cfg.<路径>` | 数字 | - | 覆写 fxConfig 任意参数，如 `cfg.stationViews.RACK.azDeg=-40`(面板改动自动写进 URL) |

## 定制视角(第四轮核心)

每工位机位在 [fxConfig.js](./fxConfig.js) 的 `stationViews`：`{azDeg, elDeg, fill, radiusM}`。
azDeg 0=+Z 整机正面、正角向 +X；fill 是**距离余量倍率**(1=模块贴满画面边——取景距离
按工位包围盒 8 角点沿视线精确解，数学上保证"完整看到模块")；ROBOT 用 `radiusM`
定半径只框臂体(不框整条地轨)且目标点跟机械臂当前位置。
**调参回路**：点击聚焦 → 手调到满意机位 → 面板"固化机位为该工位视角" → 三个值写回
config 并固化进 URL(`cfg.stationViews.*`)，复制地址即交付；改 fxConfig 默认值则永久生效。
巡检路线 = 世界 X 左→右全 11 站(`cfg.tour.route` 可覆写为逗号分隔 id 串)。

## 开关门

`fxConfig.doors` 定义 **8 扇**：`sideL1/sideL2`(左端对开侧门)、`feed`(前上料门=钣金框+
亚克力观察窗两件同转)、`back`(后侧门板)、`frontL1/frontL2` 与 `backL1/backL2`(前后长面
左半各一对对开门)。每扇 `{nodes, hinge, openDeg, sign, pair?}`——铰链竖边取门世界盒的
minX/maxX/minZ/maxZ，运行时插 align+hinge 双层 Group 建枢轴(门 mesh 原点在板中心，
直接转会绕中线翻)。`pair` 声明对开门的另一扇，**装配期双向补齐**，点任一扇两扇同开。

**hinge/sign 不是可调口味，是几何事实**：铰链边由 CAD 合页件 `AKQ41-G-Z-6065_*`(每扇
2 只，骑在铰链那条竖边上)定，把手 `XAD51-A100-*` 永远在对边(=自由边，即用户说的"要被
打开的那一侧")；sign 由"自由边必须朝机外走"解出。前后长面各 3 根合页立柱
X = −1.21/+0.27/+1.23，左端面 2 根 Z = −0.68/+0.67。改之前先回到这份硬件证据，
别照着屏幕猜——`feed` 与 `back` 就是按推测填错过两轮(一个挂在把手边、一个往柜内开)。
现由 `tests/three-d/fx-door.test.js` 的"门表钉死"用例逐扇兜住。

每扇门的 `nodes` = **门板 + 骑在门上的五金**(把手 + 合页门叶组)。漏了五金门照转，但
把手会明晃晃悬在关门位置(2026-08-09 用户报的 bug)。全机普查过：每扇门骑着且仅骑着
1 只把手 `XAD51-A100-N` + 2 片合页门叶，没有第三类。

这些都要能单独转，前提是在 `material_semantics.yaml` 的 `part_isolate` 里(**25 件** =
门体 9 + 把手 8 + 合页组 8)，否则会被并进静态合并块、整块只能一起动；改完要重跑管线
(至少 materials → clean → optimize-cr5)。名带"固定门板"的 4 扇一度被判为"按图纸不可开"，
那是误判。

**合页门叶的节点名是管线造的**：16 片门叶在 CAD 里同名(只靠 Blender 的 `.00N` 区分)，
而 `part_isolate` 会剥掉 `.00N` 再去重，直接写原名等于没写。故由
`blender_clean.rename_door_hinge_leaves()` 先按**几何**(门叶中心落在哪扇门的门板盒内)
改成 `DOOR_HINGE_<门键>` —— 每轮重算，与后缀彻底解耦(整机 GLB 来自 SolidWorks XR 导出，
重导会换序，后缀不可依赖)；片数/归属对不上直接 `RuntimeError`。同扇两片**故意同名**，
合并成一个 `ST_FRAME/STATIC_MAT_SOLO_DOOR_HINGE_<门键>` 节点，省一半绘制调用。

`frontL1/backL1` 的 `openDeg` 用 100 而非左端那对的 110：它靠 `feed`/`back` 那侧，
全开时门板线段离 feed 铰链 945mm(余 67mm)，110° 则只有 902mm(余 24mm)，再扣门板半厚
两扇同开就穿模。

点门开关门优先于聚焦分派；悬停门体 cursor 变手型(不出白卡)；幽灵态下门仍可点。
验收 API：`__fx.api.toggleDoor('feed') / setDoor(name, open) / doorStates()`。

## 开场扫描(v3, 第五轮)

"幽灵整机**自上而下逐像素**实体化 + 相机环绕 + 科技蓝扫描平面"：
- **双层裁剪**(渐进式, 非逐零件硬切——用户否掉了 v2)：真网格保持原材质、挂
  solidPlane 只显示分解线**以上**；共享幽灵材质的克隆层挂反向 ghostPlane 只显示线
  **以下**。线下移时每个零件被逐像素切换成实体，真网格的 material 全程不动。
- **相机环绕**：方位角从 `azFromDeg`(默认 -130°, 相对终点) 环绕到位，途中掠过正面，
  与分解线同一进度——**转到位 = 实体化完成**；终点数值上就是标准 **iso** 机位
  (=页面默认常态机位，开场结束画面即常态画面)。
- **蓝色扫描平面**：加色混合 + 网格纹理(主题色 --fx-accent)骑在分解线上跟随下扫，
  扫完 0.3s 淡出；辉光由 bloom 免费带出。
总时长 durS+tailS=3.2s，**与 main.freezeAt 的快进窗口绑定(两处注释互指)，改长必须
同步**。收尾/中止会把原材质与共享幽灵材质的 clippingPlanes 清回 null(幽灵材质与
聚焦隔离共享，残留裁剪面会切掉之后的聚焦幽灵)。扫描期间输入门控(Esc 可跳过)。

## 流程播放 / 显示设置 / 聚焦隔离

同第三轮：面板"流程播放"下拉全部可播片段(status=ok)，播放时顶栏运行指示与悬停卡
联动；"显示设置"数值与正式页一比一；聚焦隔离 ghost(默认)/hide/off，幽灵=换
mesh.material 引用到共享幽灵材质(49% 材质跨工位共享，就地改必连坐——铁律)。

## 仿真外壳

侧栏 13 项/顶栏(模式·实时在线·▶运行指示·四健康计数·站点/末端·主题·恢复布局·急停)/
3D 页签条，结构与样式逐字照抄正式页(`shell.js` 头注释记出处)；顶栏计数与运行指示
绑模拟剧本/片段播放**活数据**。侧栏/页签是惰性链接，急停/模式仿外观不接真机。
全局类零成本复用 `src/style.css`(main.js 已 import)；scoped 片段手抄进 styles.css。

## 截图效果图册

```
& C:/ProgramData/miniforge3/python.exe eit_ptlc/three_d/tools/visual_validation/shot_fx_preview.py
```

产物落 `eit_ptlc/three_d/work/previews/fx/`（18 张 + `fx_shots.json` 复现凭据）：
双机位摆拍/悬停白卡×2/聚焦定制视角×6(幽灵/隐藏/机械臂/视觉透视/中转/上样)/
开门×2(侧门对开/前后门)/片段播放×2/扫场中段/浅色/低画质/带面板。
`--only 子串` 只拍匹配的；`--list` 打印全部 URL。

程序化验收（39 条断言: 归属/门分离/外壳/无圆点/锚点/曝光/悬停/定制视角逐站/
聚焦实体/无压暗/扫场互斥/开关门/片段播放）：

```
& C:/ProgramData/miniforge3/python.exe eit_ptlc/three_d/tools/visual_validation/verify_fx_preview.py
```

## 模块结构（阶段B迁移的关键设计）

统一特效接口 `create(ctx) → { update(dt,elapsed), setStationState(id,state), setEnabled,
setParams, trigger?, dispose }`；`ctx.addFrameHook` 与 SceneManager 同名同签名。
**坐标契约**：内部(screenOf/卡片 transform)一律画布局部像素，对外验收 API(hoverProbe
入参/debugAnchors 出参)一律页面像素——`ctx.viewport()` 每帧缓存画布 rect，套外壳后
画布非满屏也不用改脚本。

- `shell.js` — 仿正式外壳 chrome(非特效层)
- `stage.js / postfx.js` — 迷你宿主与后期链(含 OutlineEffect 描边; ResizeObserver 补容器缩放)
- `cameraDirector.js` — 预设/**applyStationView 定制视角**(8 角点精确取景)/captureStationView 反解
- `stationIndex.js` — 工位运行时模型（ROBOT 动态包围盒/滑座探测与搬运跟随）
- `simFeed.js` — 确定性模拟剧本（零随机，node --test 覆盖）
- `fx/cards.js` — 悬停白卡 + 固定详情卡(圆点已退役; hoveredMesh 供门模块切 cursor)
- `fx/ghostMaterial.js` — 共享幽灵材质单例(isolation 与 intro 互斥的物质基础)
- `fx/isolation.js + focus.js` — 聚焦隔离(幽灵/隐藏)与点击分派(门优先)
- `fx/doors.js` — 开关门(铰链枢轴/开合动画/hingePoint 纯函数有单测)
- `fx/intro.js` — 开场 v3(自上而下双层裁剪扫描+环绕+蓝色扫描面) · `fx/tour.js` — 巡检(X 序路线)

测试：`node --test tests/three-d/fx-sim.test.js tests/three-d/fx-anchor.test.js
tests/three-d/fx-clip-station.test.js tests/three-d/fx-door.test.js`

## 已知限制

- 浅色主题是兼容目标非展示目标。
- 主题切换走整页 reload；面板最小化态不持久(刷新还原)。
- `quality=low` 无辉光无描边（与正式页 low 档"不走后期"一致）。
- 门动画走真实时间, freezetime 冻结时不推进(截图开门态用 api 开好再 settle)。
- captureStationView 不捕捉平移过的目标点(truck 偏移), 首版接受。

## 阶段B合入路径（效果确认后）

- 外壳不用搬——正式页本来就有；沙盒外壳只是预览道具。
- 卡片层 → `twin/overlay/StationCards.js`（悬停/详情卡内核不改），位置走
  `SceneManager.addFrameHook`，状态走现成 `stationHealth` + 在 TwinFeed 补 `stationAction`
  低频桥（vm_node_enter x actionPrefixes 反查）。
- 聚焦/隔离/描边/定制视角 → `twin/scene/fxpack/`：ghostMaterial+isolation+focus 内核
  + cameraDirector.applyStationView(视角表进 manifest 或 displaySettings)；SceneManager 增
  `attachFxPack/detachFxPack`；壳挂载经 TwinBindings 统一入口（防材质克隆互顶）。
- 门/开场 → fxpack 可选件（门定义表可下沉进 manifest 的 doors 段）。
- 开关：DisplayPanel `DISPLAY_FIELDS` 增"增强显示"分组；`QUALITY_TIERS` 各档加 fxpack
  字段（low/lite：描边/扫场不建，悬停卡保留）。
- 合入后 `npm run build`（18080 的 dist 才可见）+ verify_twin.py 无回归。
