# 视觉 UI 调参闭环四切片设计 (2026-07-11)

## 背景与问题

拍照刮板流程与"视觉"栏(视觉调试台, `/vision` 路由)存在四个用户痛点:

1. **HITL 门弹窗及中间图片尺寸屡修未果。** 根因已定位:全局 `web/src/style.css:334` 给 `.modal` 写死 `width: 420px`;而 `HitlModal.vue:363` 的 `.modal-wide` 只设了 `max-width`(现 `min(96vw,1500px)`)从未覆盖 `width`。CSS 中固定 `width` 赢过更大的 `max-width`(used width = min(420, 1500) = 420px),故 sketch/reanalyze 门弹窗实际永远 420px 宽,3088×2064 原生图被压到约 372px(≈12%)。历史两次修复(`5b55a83` 引入 max-width 加宽、`194b8f7` 提到 1500px/80vh)全部是死代码。
2. **视觉栏图片无放大方式。** 6 张图(before/after 原图、双质量叠加、annotated、score)全是普通 `<img>` 限高 260~360px(`VisionDebugView.vue` scoped CSS),bandid 标签、Rf 文字看不清。
3. **调参闭环缺"最后一公里"。** 骨架已建好:重识别门已有 4 参数输入(`HitlModal.vue:296-315`)、`POST /api/photoscrape/reanalyze` 已通(`photoscrape_routes.py:121-164`,走与 VM 同一条 live-read+覆盖路径)、视觉栏已有同 4 参数"识别参数"区 + "应用到生产"(写回 `config.vision`,生产每次分析实时读盘)。缺口:① `image_plate_rotation_deg` 未纳入调参面(后端 `analyze_action` 其实已支持该覆盖,`vision_controller.py:512,546`);② 视觉栏无法一键载入生产 run 的 before/after 复盘;③ 弹窗与视觉栏参数 UI 各写一份;④ 重识别门占位符只写"基线"不显示实际值。
4. **叠加图颜色语义无图例。** 质量叠加图(`vision_quality.py::_generate_overlay_cv:760-881`)的绿框=板轴对齐外接框(质量统计 ROI)、黄框=板旋转矩形四角(转角/偏斜证据),**都是板级几何,均非 band**;band 画在识别标注图(`vision_controller.py::_generate_annotated_image_cv:684-909`)上,轮廓常量名 `CONTOUR_MAGENTA` 但 BGR `(54,132,255)` 实际渲染为**橙色**。用户无从分辨。

范围决策(用户已确认):**方案 A** —— 只打磨现有旋钮面,不参数化 `tlc_analyze` 算法内部阈值(绿板掩膜、min_width_fraction 等留待未来单独立项)。

## Global Constraints(逐字复制进每份子 plan)

- 只改 `eit_ptlc/` 活跃树;`View/pTLC_Viewing/tlc_analyze.py` 本次**只读**(方案 A 不动算法内部)。
- 参数空值语义:前端 `''` = 不覆盖/用基线;`0` 与 `0.0` 是合法值必须透传(沿用 `p.x !== '' && p.x != null` 判式,防 None-sentinel 零值坑)。
- `image_plate_rotation_deg` 语义:`null` = 每帧自动估计;写回 config 时允许 null(`VisionCfg` 字段本为 Optional)。
- 不破坏 run-vs-edit 解耦不变量(浏览/调参不得终止运行中的 run)。
- 后端改动须有离线 pytest 覆盖,现有全量离线套件保持全绿;前端无测试设施,`npm run build` 必须通过。
- UI 文案中文,风格沿用现有自研组件(无 UI 组件库)。
- 新文件服务端点必须有目录穿越防护与后缀白名单(沿用 `vision_routes.py` / `vision_debug_routes.py` 现有模式)。

## 切片 1:HITL 弹窗尺寸(根因修复)

**改动(全在前端 CSS/模板):**

- `HitlModal.vue` scoped `.modal-wide`(:363)改为:
  ```css
  .modal-wide { width: auto; max-width: min(96vw, 1500px); }
  ```
  scoped 选择器(class+data 属性)特异性高于全局 `.modal`,能真正覆盖固定宽。`width: auto` 让图片内容自然撑开、上限封顶,竖图不留大片空白。
- 全局 `style.css` `.modal`(:334)加 `max-height: 92vh; overflow: auto`(防高图纵向溢出视口)。
- 全局 `.hitl-img`(:337)加 `max-height: 72vh; object-fit: contain`。
- 加宽条件(`HitlModal.vue:265`)从 `kind==='sketch'||kind==='reanalyze'` 扩展为**凡带图的门都加宽**:`kind==='sketch' || kind==='reanalyze' || !!debug.hitl.image`。
- 历史"死代码"修复(1500px / sketch-wrap 80vh)在宽度打通后自动生效,不回退。

**验收:** reanalyze/sketch/带图 confirm 门中,3088×2064 图在 1080p 屏上显示宽度 ≥ 1200px;弹窗不超视口、内部可滚动;无图的 input/confirm 门维持 420px 原样。

## 切片 2:通用图片放大(ImageLightbox)

**新组件 `web/src/components/ImageLightbox.vue`**(自研,Teleport to body):

- 契约:props `{ src: string, alt?: string }`,`src` 非空即显示;事件 `close`(父组件置空 `lightboxSrc`)。每个视图持一个 `lightboxSrc` ref,现有 `<img>` 加 `@click="lightboxSrc = <url>"` 与 `cursor: zoom-in`,布局零改动。
- 交互:滚轮以光标为中心缩放(适配尺寸~8×);拖拽平移;双击在"适配 / 1:1"间切换;Esc 或点背景关闭;角落工具条显示缩放百分比 + 「适配」「1:1」「原图」(新标签页打开原始 URL)按钮。实现用 CSS transform(translate+scale),不用 canvas。
- 接入点:`VisionDebugView.vue` 全部图片(image-box :509-512、overlay-box :513-516、result-images :555-564)+ `HitlModal.vue` 的标注/预览图(:316-317、:338)。**手绘 canvas 不接**(交互画布)。

**验收:** 视觉栏任意图点击后可放大到 1:1 看清 bandid/Rf 标签;弹窗内标注图同样可放大;Esc 关闭后不影响门的状态。

## 切片 3:调参闭环打通(方案 A)

### 3.1 第 5 参数 `image_plate_rotation_deg` 纳入全链

后端 `analyze_action` 已支持覆盖(`vision_controller.py:512,546`),补齐其余环节:

| 环节 | 文件:位置 | 改动 |
|---|---|---|
| 调试台参数集 | `controller/vision_debug_service.py` `_RECOGNITION_KEYS`(:23-28) | 加 `image_plate_rotation_deg`(可为 null) |
| 调试台播种 | `runtime/bootstrap.py`(:273-278) | recognition_defaults 加该键(取自 config.vision) |
| 应用到生产 | `api/vision_debug_routes.py` apply_to_production(:93-121) | 写回 payload 加该键(null 合法) |
| 重识别路由 | `api/photoscrape_routes.py` reanalyze 透传元组(:154-155) | 加 `"image_plate_rotation_deg"` |
| action 旋钮 | `config/actions/04_photoscrape/vision.yaml` | 加 `{name: image_plate_rotation_deg, type: float, required: false, min: -180, max: 180, label: 相机滚转角覆盖 (deg)}` |
| 视觉栏 UI | `VisionDebugView.vue` 识别参数 fieldset(:446-485) | 可空数字输入,空=自动估计(显式提示) |
| 重识别门 UI | `HitlModal.vue` reParams(:30,:49)/reOverrides(:211-219)/模板(:296-315) | 加输入项,空=基线 |

### 3.2 一键载入生产 case

- **`GET /api/vision/debug/cases`** → `{cases: [{id, summary_dir, mtime_iso}], truncated}`。扫描单根 `config.vision.output_dir`(vision_output;已核实 `with_output_dir` 在活跃树无调用者,其 docstring 提到的 ScrapeStage/SampleStore 切换是陈旧引用,生产 analyze 全部落在该目录);case = 含 `inputs.json` 的子目录;按 mtime 倒序,截断 50 条(截断时响应带 `truncated: true`)。
- **`POST /api/vision/debug/load_case`** body `{summary_dir}`(取自列表项)→ 读该目录 `inputs.json`,校验 before/after 文件仍存在,复用调试台上传路径逻辑拷入工作区(同时算质量叠加),state 的 `source` 记 `case:<id>`。防穿越:解析后必须仍在上述两根之一。错误:404 目录/inputs.json 缺失;404(明确文案)图片文件已被清理。
- **UI:** `vd-images` 区上方加一行:case 下拉(label=id+时间)+「载入」+「刷新列表」。载入后 before/after 同时替换。
- **完整闭环:** 生产 run 识别不满意 → 视觉栏载入该 case → 调参分析迭代 → 应用到生产 → 回 HITL 门「重新识别」(留空即用新基线)→ 选带「用此结果」下发。

### 3.3 共用参数组件 + 基线占位

- **新组件 `web/src/components/RecognitionParams.vue`**:渲染 5 个识别参数控件。props:`modelValue`(参数对象)、`mode: 'value' | 'override'`、`baseline?`(对象);事件 `update:modelValue`、`change`。`value` 模式(视觉栏)= 有类型的当前值;`override` 模式(重识别门)= 空串表示"用基线",占位符显示 `基线 <实际值>`。
- 视觉栏"识别参数" fieldset 内部替换为该组件(change → 现 `markRecognitionDirty`);重识别门参数区替换为该组件,门打开时经现有 `api.getConfigSection('vision')`(`api.js:149`)拉一次基线传入。

**验收:** 五参数在视觉栏、重识别门语义一致;重识别门能看到基线实际值;载入生产 case → 调参 → 应用到生产 → 门内重识别用新基线,全链路人工走通;`rotation=0` 能作为覆盖值透传(非被当作空)。

## 切片 4:叠加图图例

- **`web/src/overlayLegends.js`**:导出 `QUALITY_LEGEND` / `ANNOTATED_LEGEND` 数组 `[{color, label, note?}]`,色值按**实际渲染色**(BGR→RGB 换算),注释注明 Python 源(`vision_quality.py:776-782`、`tlc_analyze.py:33-45`)防漂移:
  - 质量叠加:绿 `rgb(0,220,0)` 板外接框(质量统计 ROI)· 黄 `rgb(220,220,0)` 板旋转四角(转角/偏斜)· 红 `rgb(220,0,0)` 板中心十字 · 青 `rgb(0,220,220)` 四边留白 · 白 画面中心与曝光统计。附一句关键说明:"**此图只评估拍照质量(板几何/曝光),不含 band;识别结果见标注图**"。
  - 识别标注:橙 `rgb(255,132,54)` band 轮廓(常量名 CONTOUR_MAGENTA 是误称,以渲染色为准)· 青 `rgb(0,216,236)` 刮取路径 · 白 十字=band 质心 · 灰白 板边界框 · 标签 = `band_id (O=origin) · Rf`。
- **新组件 `web/src/components/OverlayLegend.vue`**:props `{ type: 'quality' | 'annotated', compact?: boolean }`,渲染色块+短文案。
- 挂载:视觉栏"质量叠加"图下、annotated 图下;重识别门标注图下(compact)。

**验收:** 两类图下方均有图例;色块与图上线条颜色目视一致;"黄框绿框谁是识别用"不再需要口头解释。

## 数据流与错误处理(汇总)

新增后端面仅切片 3 的两个端点(只读列表 + 拷图入工作区),复用 `vision_debug_routes` 白名单/防穿越模式,缺 inputs.json、图被清理均返回带明确中文文案的 4xx。Lightbox/图例纯展示,无新状态源、无轮询。rotation 透传沿用现有 None 语义与 `_parse_vision` 校验。

## 测试策略

- 离线 pytest(镜像 `test_vision_apply_to_production_offline.py` / `test_photoscrape_reanalyze_offline.py` 套路):① cases 列表(两根扫描/排序/截断);② load_case 正常 + inputs 缺失 + 图被清理;③ reanalyze 透传 rotation(含 `0.0`);④ apply_to_production 含 rotation(含 null)。现有全量离线套件保持全绿。
- 前端:`npm run build` 通过;Playwright 手动验证弹窗宽度、Lightbox 交互、图例渲染。
- 真机验证(HITL 门实弹)留待下次上机,单列 checklist。

## 实施拆分(供 writing-plans)

拆两份独立 plan,各自可独立编译/自测:

- **Plan 1「展示层」= 切片 1 + 2 + 4**:纯前端(HitlModal/VisionDebugView/新 Lightbox/图例),无后端改动。
- **Plan 2「调参闭环」= 切片 3**:后端两端点 + 5 参数全链 + RecognitionParams 组件 + 基线占位。

依赖:Plan 2 的 HitlModal 参数区改动建立在 Plan 1 的弹窗加宽之上,**先落 Plan 1**。Global Constraints 逐字复制进两份 plan。
