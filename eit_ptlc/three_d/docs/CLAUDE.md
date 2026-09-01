# PTLC 三维可视化 —— AI 协作说明

> 本文件是 `three_d` 目录的工作约定. 任何新的 AI 会话开始前先读它, 即可对齐上下文.
> 目标读者是接手本项目的 AI 助手与人类审查者.

## 一句话定位

把 PTLC 自动化设备的 SolidWorks 图纸转成 Web 可加载的三维模型, 在浏览器里以
"深色科技控制台"风格展示整机, 绑定上位机的实时遥测, 并支持点击工位执行动作.

## 目录职责

| 路径 | 职责 |
|---|---|
| `mcp_servers/sw_mcp/` | SolidWorks MCP 服务器. `sw_constants` 从 swconst.tlb 读常量, `sw_core` 是 COM 封装(可独立当 CLI 用), `server.py` 是 MCP 包装 |
| `mcp_servers/blender_mcp/` | Blender MCP 服务器. 无界面驱动, 支持检查模型/执行 bpy 脚本/渲染预览/跑清理步骤 |
| `pipeline/` | 资产管线脚本 01~05 + 配置(prune_list / materials / rig_map / flow_params) |
| `exports/` | SolidWorks 导出的 STEP(AP214, 带颜色) |
| `work/` | 中间产物: 改名后的 STEP、raw GLB、预览图、各步骤报告 JSON |
| `models/` | 最终交付资产: `machine.glb` / `cr5.glb` / `device-manifest.json` |
| `../web/src/three-d/` | 上位机内的装配、材质、动作、演示、实时五个三维工作台. 动作台内含运动模式/标定/原子动作演示三个子页(共用一个 SceneManager, 切子页只挂拆驱动栈); 演示台自动关联全部流程 |
| `clips/` / `generated/` | 动画片段与前端生成数据. `clips/flow-index.json` 是流程动画台账(每条流程的精编译结果与失败原因), `generated/action-motion-map.json` 是"动作→机构"映射表的**单向导出**(真源在 clip_compiler, 前端只读不抄) |
| `tools/visual_validation/` | 面向上位机 `/3d/*` 路由的浏览器验收工具 |
| `docs/` | 本文件与里程碑记录 |

## 硬约束(踩过坑, 别再踩)

1. **中间文件路径必须是纯 ASCII.** OCCT/cascadio 的 C++ 层在 Windows 上按 ANSI 代码页
   解析路径, 含中文的路径直接报 `Cannot open input file`. 所以 01 步会把文件名 slug 化.

2. **STEP 里的中文是裸 cp936 字节**, 不是 ISO-10303-21 的 `\X2\` 转义. 直接喂给 OCCT
   会得到乱码. 01 步负责解码并转成拼音, 真正的中文名保存在 `work/*_names.csv`.

3. **装配实例名必须回填, 否则 GLB 节点全叫 `NAUO1234`.** SolidWorks 写出的
   `NEXT_ASSEMBLY_USAGE_OCCURRENCE` 的 name 字段是空白, OCCT 只好退回用 id 字段命名,
   于是 2000 多个节点全无语义, 删减规则/材质规则/装配映射会同时失效.
   01 步顺着 `NAUO.related → PRODUCT_DEFINITION → ..._FORMATION → PRODUCT` 取出真名回填.
   **验收标准: `05_report.py` 的"语义命名占比"应接近 100%.**

4. **绝不干扰用户的 SolidWorks.** 一律只读打开; 只关自己开的文档; 只往 `exports/` 写.
   动手前先用 `sw_info` 确认没有别的任务正在占用(看 `open_documents` 有没有未保存标记).

5. **不要用 gltfpack 替代 gltf-transform.** gltfpack 会重命名/折叠节点, 而
   `device-manifest.json` 靠节点名绑定实时数据, 名字一改整条绑定链就断.

6. **前端算包围盒必须用 `Box3.setFromObject(obj, true)` 精确模式.** 默认快速模式取
   几何体缓存的局部 AABB 再变换角点重新拟合; 而 04 步的 `KHR_mesh_quantization`
   会把每个图元的局部包围盒变成量化立方体, 旋转后重新拟合会明显膨胀 ——
   实测把 2.64×2.10×1.53 m 的整机报成 4.01×3.64×3.98 m, 导致自动取景把相机拉远
   近一倍. 见 `../web/src/three-d/twin/scene/loadModel.js` 的 `computeBounds`.

7. **删减的尺寸阈值在 `normalize_units()` 之后换算.** 归一后场景恒为米,
   毫米阈值一律除以 1000. 早期版本按"原始单位是否为毫米"分支换算, 结果在已经是米的
   模型上把 6 mm 阈值当成 6 m, 一次性删掉了 94% 的网格.

8. **MCP 目录不能叫 `mcp`.** 会遮蔽同名 pip 包, 任何以 `three_d` 为工作目录的脚本
   都会 `import mcp` 失败, 故命名为 `mcp_servers`. 另外 MCP SDK 2.x 的高层服务器类
   是 `mcp.server.mcpserver.MCPServer`(1.x 时叫 `mcp.server.fastmcp.FastMCP`).

9. **Blender 里新建对象后必须先 `bpy.context.view_layer.update()` 再读 `matrix_world`.**
   它是惰性求值的; 刚设完 location/scale 就读会拿到旧值(通常是单位矩阵), 回写等于把设置
   抹掉. 现象是状态灯与液面盒全部缩回原点、尺寸变成 1, 还会撑大所属工位的包围盒.
   见 `blender_clean.py::reparent`.

10. **Blender 是 Z 轴向上, glTF 是 Y 轴向上.** 导出结构清单时必须转换
    `(x,y,z)_blender -> (x,z,-y)_gltf`, 否则下游算相机机位会用错高度分量.

11. **包围盒一律逐顶点算, 不要用 `bound_box` / 非精确的 `Box3`.** 旋转过的局部 AABB
    重新拟合会明显膨胀(实测把 2.6×1.5×1.0 m 的机架报成 3.9×3.7×2.1 m). CAD 导入的零件
    普遍带任意旋转, 这个坑在 Blender 侧和前端侧各踩过一次.

12. **改材质属性前先克隆.** 管线按"工位 × 材质"合并, 但材质对象在各工位之间是共享的;
    直接改共享材质(如外罩透视要改 opacity)会波及所有用同种材质的零件, 现象是整台机器
    一起变透明.

13. **集成态必须复用宿主 SPA 的事件流单例.** 同一页面开第二条 WebSocket 会让后端多一路
    订阅者且遥测被重复投递. 见 `bindings/eventStream.js` 的适配层.

### SolidWorks COM 专项(取材质时踩的)

14. **早期绑定必须在 `Dispatch` **之前**建好.** pywin32 在 Dispatch 那一刻就决定了这个
    对象用早期还是后期绑定, 之后再 `EnsureModule` 已经晚了. 见 `sw_core._ensure_early_binding`.
    另外 `CastTo` 在 SolidWorks 上基本不管用(对象不自报 CLSID), 会**静默**退回后期绑定 ——
    此时 `GetTitle` 之类基础成员照常能用, 只有具体接口的方法报"找不到成员", 极具迷惑性.
    所以 `_wrap` 一律用 makepy 生成的接口类直接包**原始 `_oleobj_`**, 并实调一次探针方法验证.

15. **同一个文档对象既是 `IModelDoc2` 又是 `IAssemblyDoc`, 换接口要 `_wrap(..., force=True)`.**
    `_wrap` 默认有防双重包装守卫(已是 gen_py 包装就原样返回), 不加 `force` 这种转换会被
    静默跳过, 表现为 `'IModelDoc2' object has no attribute 'GetComponents'`.

16. **`IComponent2` 的 `MaterialPropertyValues` 只返回"组件级覆盖", 不是零件的颜色.**
    整机 1544 个组件里只有 3 个做了组件级覆盖(都是透明件), 其余全返回 null.
    零件真正的材质与颜色要经 `IComponent2::GetModelDoc2()` 拿到零件文档再读.

17. **大装配默认按"自动轻量化"载入, 必须先 `ResolveAllLightWeightComponents` 批量解析.**
    不解析就逐个 `GetModelDoc2()`, 每个零件会现从磁盘冷开 —— 实测 **34.9 秒/零件**,
    749 个唯一零件要跑 7.3 小时. 批量解析是一次调用, 之后每个 `GetModelDoc2` 命中内存.

18. **SolidWorks 会在某些调用上自旋不返回, 而且掐掉客户端**不一定**能让它停下来.**
    确认中招的两处: `IAssemblyDoc::GetComponents(False)`(必现, 换递归遍历即可绕开),
    以及递归遍历中某个组件的 `GetModelDoc2()`.
    识别特征: CPU 满一个核、内存基本不涨、磁盘读速几百 B/s、无模态框、`Responding=True`
    —— 光看"进程有响应"会误判成正常. 第一次掐客户端后 CPU 立刻归零, 第二次却又空转了
    半小时才自己恢复, 所以**不能指望掐进程来止损**.
    对策(已落进 `extract_part_colors.py`): 每读 50 个零件增量落盘;
    把"正在读哪个"实时 fsync 进 `work/part_colors.trace.log`(卡死时最后一行就是元凶);
    支持按路径 `--skip` 绕开与 `resume` 续跑; 外面再套一个"trace 90 秒不增长就收手"的看门狗.

19. **`Extension.SaveAs(ExportData=None)` 这条静默导出路径恒定写出 AP203.**
    实测把 `swStepAP` 与 `swStepExportPreference` 遍历 0~3 全试一遍, 8 次导出的
    `FILE_SCHEMA` 全是 `CONFIG_CONTROL_DESIGN`(即 AP203), `COLOUR_RGB`/`STYLED_ITEM`
    一个都没有. 也就是说**走 STEP 拿颜色这条路在本环境下是死的**, 材质只能走 COM 逐零件读.
    偏好项本身是设进去了的(回读确认), 只是导出器不读它.

20. **模型侧的零件名有两种写法, 而且会被截断到 47 字符.** 01 步只改**中文**名, 纯 ASCII 名
    (`_HFD12X10(CL)_b`、`14-BODY_6^...(2)_...`)原样透传进 GLB, 连 `^` `(` 都保留.
    所以按零件名匹配材质时, 原名与 slug 两种写法都要发, 且长名要补一份 `[:47]` 的截断写法.
    实测这样能覆盖 GLB 里 **98.4%** 的带网格节点.

21. **有三份模型(六个部署文件), 部署时别只更新一部分.** 装配工作台加载
    `models/raw.glb`(**未删减**的原始模型 + 官方臂替换: 03 的 `--stage raw`
    做换臂并整机赋管线材质(2026-08 起; 此前保持 CAD 原貌, 但原生材质 68.6% 白/灰,
    指认视图像白模), 其余零件保持**全量与点选粒度**供删留裁决. raw 的臂放在
    **CAD 原摆放位**(黑色安装座上, 非标定参考轨位)并**烘焙 robot-main.home 姿态**
    (公式与前端 RobotJointDriver 一致); 底座电缆航插**保留** —— 装配台语义是全量零件.
    正式产物则相反: full 链经 `strip_base_connector` 删掉航插(减配), 臂在参考轨位
    挂 CARRIAGE 下、零位交给前端驱动. 即"装配=全量 ⊇ 材质=减配"),
    实时工作台(`/3d/live`)加载 `machine.glb`(清理后的成品), 动作工作台(`/3d/motion`)加载
    `machine.official-cr5.glb` + `device-manifest.official-cr5.json`(官方 CR5 灰度
    两件套, 见 CR5_DIGITAL_TWIN.md 的发布边界). 它们来自管线不同阶段/不同 04 参数,
    `deployAssets` 与重跑步骤必须**全部覆盖**(official-cr5 两件套 2026-08-01 已并入,
    此前靠手工 Copy-Item, 漏拷过一次). 漏掉的现象极隐蔽: 某个视图已是新模型、另一个
    还停在上一版, 观感/点选对不上, 且不报任何错.
    raw 链是两步: `03_clean_model.py --stage raw`(Blender 换臂+赋材质, 产出
    `work/machine.raw.glb`, 报告/作业单用独立文件 `03_raw_swap.report.json` /
    `_blender_job_raw.json`, **不覆盖** full 链给 gen_twin_manifest 读的同名产物)
    → `04_optimize.mjs --passthrough`(只转码为 meshopt, 不简化/合并/删减;
    前端只装了 `MeshoptDecoder`). 读 Draco 输入须注册 `draco3d.decoder` 依赖,
    且读完要 `dispose()` 掉 Draco 扩展, 否则写出时会反过来要求 `draco3d.encoder`.
    注意: 装配台对 `CR5_*` 官方臂节点做删减授权**不会生效**(prune 在换臂之前执行),
    臂是整体替换件, 本就不参与删留授权.
    第六个部署文件是 `merge-members.json`(03 full 启动器从 `join.members` 派生到
    `models/`): 材质台在生产构建下的
    合并成员反查/命中候选全靠它, 漏拷的现象同样隐蔽 —— 成员清单显示的是上一版
    的块结构, 名字对不上且不报错. 手动重跑后记得一并拷贝.

22. **`python` 在本机 PATH 上是 Windows 应用商店的空壳**(退出码 49, 无任何输出).
    跑本项目的脚本一律用 `C:\ProgramData\miniforge3\python.exe`.

23. **不带 `--input` 的 03 步曾静默退回 STEP 旧模型.** `pipeline.yaml` 的
    `model_source: native_glb` 开关一度只写在注释里没实现, 03 的默认输入写死了
    legacy 产物 —— 于是"vite 插件重跑"与任何省略 `--input` 的调用都会用旧模型:
    少 3 个总成、原生外观命中 0、兜底数 1352, 且一路绿灯不报错. 已修
    (03 现在按 model_source 解析默认输入), 但**验收时务必看日志第一行的输入路径**,
    以及"来源 ... 原生外观=N"里 N 是否为 0.

24. **材质规则分两个宿主, 校准观感要改两处.** 按 CAD 材质名/原生外观的规则在
    `material_semantics.yaml`(由 `build_materials.py` 编译进 materials.yaml);
    而按**零件名**的角色规则(MAT_STEEL_PLATE/MAT_COVER/MAT_LINEAR_MODULE …)住在
    `pipeline/materials.yaml` 的 `rules` 段, build_materials 只是**逐代原样携带**它,
    不从语义表再生 —— 它们优先级还压过原生外观(第 4 级 > 第 5 级), 覆盖 500+ 对象.
    只改语义表会漏掉整机最大头的钣金/型材/罩板. 另注意 materials.yaml 是生成物,
    手写注释会在下次 build_materials 时被抹掉, 但 rules 的**数据**会保留.

25. **材质是「物性 × 颜色」两个颗粒度, 绝不能用规则把颜色碾平.** 曾经"每条规则一种
    共享材质"导致夹爪金色快换(#FFC400 的 PEEK 接头)、门板 α=0.2 全被单色规则盖掉,
    用户对照实物一眼判死: "装配图(原生模型)比材质图还好看". 现行算法(blender_clean.
    assign_materials): 物性按类(规则只出金属度/粗糙度模板), 颜色按件(原生基色直采,
    **含白灰** —— 白也是信息), CAD 标错的色走 `native_color_passthrough.recolor`
    纠错表, "颜色即语义"的规则(拖链黑/机械臂分层)标 `force_color: true`.
    实例名 `MAT_<类>_<HEX>[_Axx]`, 颜色量化 8 级步长约束绘制调用.

26. **审计先行, 目检收尾.** 动材质前先跑一遍原生颜色清单(headless Blender dump →
    work/native_inventory.json): 本机实测无绿色件(用户看到的"绿柜"是别的问题)、
    青色 #00FFFF ×174 是 CAD 标记色(含旋转环, 非全是管件)、DOBOT 24 网格全白(层次
    要按 -BODY_/-COVER_/-TRIM_ 命名人工授色)、SolidWorks 只给 2 种材质写 alpha.
    改完必须跑 `tools/visual_validation/review_visual.py`(经 window.__ptlc 开发钩子隔离取景)出 5 机位
    + 6 点名区域截图, **逐张对照实物照片过检查单**, 交互验收(verify_materials.py)
    只证明通路, 不证明"长得对".

27. **three.js 会消毒节点名(空格→下划线等), 浏览器侧名字不可直接与 Blender 侧比对.**
    实锤案例: Blender 原名 `为盛机电␣␣F050SH…支架-1`(两个空格) 在网页里变成
    `为盛机电__F050SH…`; 工作台把 three 名写进 explicit_delete 后, prune 精确比对
    0 命中 —— "标了删除、重跑后还在", 且日志只写"显式 0 个"无人察觉. 三道防线:
    (1) 加载后把 glTF 原名存进 `userData.origName`(loadModel), 名单一律写原名;
    (2) blender_clean.prune 对显式名单做空白→下划线归一比对(旧条目也能命中);
    (3) 名单条目未命中任何对象时必须打"显式名单未命中"警告 —— 静默失败不许再有.
    另注意 three 给无名网格起的 `mesh_N` 自动名在 Blender 里不存在, 这类条目靠
    其父装配节点的子树删除覆盖.

28. **供应商单体网格里的线缆/插头, 用 `prune_list.yaml` 的 `region_delete` 段做局部删除.**
    实锤案例: 刮板 Z 轴模组 CFG4-L5-50 的数模是单体 STEP 导入件(节点
    `Open CASCADE STEP translator 7.6 18.2-1`), 电机+滑块+丝杆+线缆+插头同属一个
    网格 —— 装配台点哪都是选中整件, explicit_delete 也只能整件删. region_delete
    (blender_clean.region_delete, 排在 prune 之后、decimate 之前)按"零件**局部坐标**
    毫米区域框"删几何, 且**整个连通面岛完全落进框内才删**: 这类网格顶点未焊接,
    线缆/插头天然是独立面岛, 框画宽松也只会命中它们, 机身岛延伸到框外即豁免.
    三个注意: (a) 局部坐标与实例摆放无关, 同名零件全部实例一次生效; (b) 框坐标由
    AI 在 Blender 里探测面岛包围盒、渲染前后对比核对后写定, 不要肉眼猜数;
    (c) 装配台的 raw.glb 不做删减(仅换官方臂与赋材质), 被删的线在点选界面里**仍然可见**,
    只有演示视图的 machine.glb 里消失(与第 21 条"三份模型"同一语义); 2026-08-05 起
    raw 阶段改跑 `region_split()`, 把同一批面岛**分离**成 `<节点名>__REGION_DELETE` 的
    独立对象而不是删掉 —— 线还在原位, 但成了可点选、会被标红的节点(见第 38 条).
    (d) 排查"哪些供应商件带模制线缆"时**别把 work/native_inventory.json 当完整清单**
    (实测漏了 CFG4-L5-300 整个模组), 枚举一律在 Blender 里对 GLB 本体扫 `*_3D模型`
    装配. 同厂不同型号的电机端常是同一份网格(面数/岛分布逐项一致即可确认),
    区域框可原样复用或按机身长度差平移; 电机组拆成多个叶子件的(如 CFG4-L5-300
    的管身/插头), 整删件走 explicit_delete, 只有"与电机同网格"的部分才动 region_delete.

29. **供应商直线模组的 336 个 `Open CASCADE STEP translator 7.6 N.M-1` 网格,
    材质按 OCC 数字索引写死在 rules 段(2026-07-31 地轨/滑轨/电机修复).**
    数字首段唯一标识模组家族: 2/18/133/138=丝杆模组(CFG4/12), 19=机器人地轨(CFF10),
    82=输送模组(CFG5), 178/181=CFC30B 皮带/同步带模组; 且 `N.2-1` 在各 CFG/CFF 家族
    里恒为**电机总成**(18/82/138 是同一个 17262 面的 T100W 网格). 三分法:
    黑色端块+电机+皮带 → MAT_BLACK_MODULE 前置扩展条目(精确索引, 如 `7\.6[ _]19\.2-`),
    防尘薄盖板(0mm 厚 12~540 面) → MAT_MODULE_TOP, 其余 → MAT_LINEAR_MODULE 家族兜底
    (数字白名单, 新家族不会静默吃进外壳色). 这批件原生色全是纯白, 规则**必须
    `force_color: true`**, 否则颜色轴仍直采白色(= 修复前的病根). 滑台是活动件
    **不许涂黑**(19.1.14 地轨滑台板 / 178.2.1.5、181.2.1.5 皮带滑台 / 133.1.5.1.*
    CFG12 滑台), 曾把停在端部的滑台误判成端块. 判类依据(逐网格几何特征+目检定稿)
    落在 `work/module_zones.json` 的 curated 段, 调试着色渲染在
    `work/previews/dbg_fam*_iso.png`. 配套名字规则: LRM 导轨条/滑块 →
    MAT_GUIDE_RAIL/MAT_GUIDE_BLOCK; 42CM08 步进电机子件用 `-3-1` 后缀锚定归黑;
    TW[ABDHM] 拖链、`tong_bu_dai` 橡胶带归黑; 电缸(IDC31/E-CXA01/IAJ41/E-EIM01)
    整体外壳金属(4 个 primitive 认不出电机段, 未强分). **重新从 SolidWorks 导出
    GLB 后 OCC 编号可能重排**, 须按 module_zones.json 的几何特征重新核对索引规则
    再信任本条.

30. **材质台写回的 `appearance_overrides` 键是最终材质实例名, 透传别按前缀过滤.**
    实例命名是 `MAT_<类>_<HEX>[_Axx]`(blender_clean.material_for 现造), build_materials
    的 `apply_overrides` 把未命中规则段的键全部塞进 `native_color_passthrough.overrides`
    由 Blender 侧按实例名套用. 旧版这里只认已废弃的 `MAT_NAT_` 前缀, 三条罩板覆盖被
    **静默丢弃**: 材质台(dev 运行时叠加, MaterialsView "恢复上次调好的覆盖")看着已生效,
    GLB 里却没烘进去, 动画/演示视图整机偏灰, 查了半天渲染设置其实两页完全一样.
    现在 blender_clean 在烘焙收尾会打"人工覆盖 套用 N/M 条", 未消费的键必告警 ——
    看到告警别忽略, 那就是"调了却不生效"的前兆.

31. **"CAD 里没包成子装配" ≠ "几何不存在". 判缺失前必须按零件号扫散落节点.**
    实锤案例: 1 号玻璃吸盘工具被文档与代码注释一致地记为"只有工位快换接口、缺少完整
    工具几何", 于是 `sync_ptlc_robot` 对 `--tool-id 1` 硬失败、manifest 不声明它、
    `syncMountedTool` 静默返回 missing —— 现场表现是上位机报 `mounted_tool=1` 而前端
    法兰上空空如也. 实际零件(QT2091392 工具侧快换 / PTLC-07-006·007·008·009·010 安装板组 /
    HRQ10A 旋转气缸 / 两个 SAB22-KQ2E06 吸盘)**一直都在模型里**, 只是 CAD 侧
    `吸盘夹具支架/` 只有一个把工具与料架混在一起的 `玻璃夹具支架装配.SLDASM`, 没有像另外
    两把刀那样拆成"XX夹具总装(工具) + XX夹具支架总装(料架)"; `build_tools` 当时只支持
    `root: {contains}` 抓单棵子树, 抓不到散件, 安装板还被 `join_static_per_station` 并进了
    `ST_TOOLING/STATIC_*`, 于是被一路误判成"缺件". 三条对策:
    (a) rig_map 的 `tools` 支持 `members: [...]` 聚合散件, 只收"尚未被前序工具认领"的对象
    (同一零件号三把刀共用时靠这一点收敛, 别指望 `.002` 后缀 —— `_base_name` 会剥掉它);
    (b) 声明了却匹配不到时**硬失败**, 不再 `log("警告")` 后继续;
    (c) 结论写进文档前, 先在 GLB 里按零件号/装配号扫一遍散落节点再下判断.

32. **换刀的 `mount_transform` 缺省会退回单位四元数, 工具绕安装轴错转约 90°.**
    大夹爪(2 号)与小夹爪(3 号)先后栽在这里. 三个工具侧 QT2091392 在 CAD 工具站里共用
    同一坐标朝向(`calibration/cr5_ptlc_v1.yaml` 的 `dock_frame_rotation`), 快换耦合是
    纯机械量, 因此三把刀共用 2 号刀在 `robot.tool_pickup` 锁紧瞬间标定出的那一组值.
    这是可证伪的几何假设, 所以 `blender_clean._check_dock_frames` 把它做成会失败的断言
    (同朝向 < 0.5°、共线 < 1 mm; 实测 `0.0396°` / `0.0 mm`), 而不是留在注释里.
    `../web/tests/three-d/manifest.test.js` 另有一道"每把刀都必须带 mountPosition+mountQuaternion"的锁.

33. **高档画面的表面"麻点/灰尘"先怀疑 SSAO, 用显示面板二分, 判据必须是目检放大图.**
    2026-08-01 用户报"表面麻麻赖赖的小点点", 对照矩阵(`app/diag_speckle_matrix.py`,
    产物 `work/previews/speckle/`)实锤: 只关环境光遮蔽麻点即消失, 关实时阴影/换 no-join
    模型都无感 —— postprocessing 6.39.x 的 `SSAOEffect` **没有任何降噪 pass**, 噪声由
    采样端参数直接决定: `intensity` 是噪声的线性放大器(合成端 `ao=clamp(ao*intensity)`),
    `radius` 是"相对 AO 缓冲高度的比例"(0.05 在 DPR2 下折 ~100 屏幕像素半径, 9 采样严重
    欠采样), 噪声再被 8 位半分辨率 RT + 法线不连续处的最近邻上采样钉成硬点. SMAA 救不了
    它(边缘检测跑在 EffectPass 输入 buffer 上, 结构上看不见同 Pass 合成的 AO 噪声).
    修复落点只在 `Effects.js`: radius 0.02 / samples 16 / fade 0.03 / luminanceInfluence
    0.7 / `EFFECT_DEFAULTS.ssaoIntensity` 1.4, 实测被动探针增量 0 ms、60 fps 不掉.
    两个次生教训: ① 椒盐类自动指标在零件密集画面里会被合法高频细节淹没(开关拨动 <2%),
    与第 26 条"目检收尾"同理, 别信数字要看放大图; ② `meshopt()` 是 reorder+quantize
    的包装且自带 14 位量化默认 —— 将来若真要动量化位数, `quantize()` 与 `meshopt()`
    两处必须同传, 只改前者会被链尾静默改回.

34. **`range_mm` 的跨度必须等于所骑模组的行程, 而模组型号里的数字才是行程 —— 本体长不是.**
    2026-08-04 前十根轴的 `range_mm` 是"控制侧 limits + 拍脑袋余量", 地轨 [0,3000] 是
    CFF10-L10-**900** 行程的 3.3 倍(动作页滑杆能把机械臂沿轨甩出 2.5 m, 而整机总长才
    2.64 m), 7Y 的 [0,400] 是 CFG4-L10-**100** 的 4 倍**且不含示教点 −20**(实机走到
    −20 会被静默钳死在 0). 病根是把模组**本体长**当成行程写进了注释(1168 mm 的 CFF10
    记成"1.17 m 行程"、880.5 mm 的 CFG12 记成"0.88 m"), 后来的人照着注释填了 range.
    三条规矩:
    (a) 行程取型号里的数字(CFF10-L10-**900** / CFG12-L5-**600** / CFC30B-S**300**…),
        并用 GLB 逐顶点实测交叉验证 —— 同族"本体长 − 行程"恒定(CFC30B 族 248.6、
        CFG4 族 192.5), 对不上就是型号认错了; 裸导轨(3Y/5Z 的自制同步带轴)取
        `_LRM<规格>RLX<长度>` 的长度数字减滑块长, 该数字实测与毫米长度 0.0 误差.
    (b) 固化进 rig_map 的 `stroke_mm`, `gen_twin_manifest.check_axis_limits` 拿它做**双向**
        校验: 跨度超行程报警; 控制侧某条 limits 跨度大于行程即判为**名义软界**(±500 的
        spotting/photo 软界、rail 的 0~3000 拒绝阈)降级为提示 —— 照抄它们等于把 range
        撑回随意状态. 示教 `value` 不参与降级, 永远硬校验.
    (c) 窗口位置在 `work/machine.full.glb`(前端加载的那份, 零位=其加载态)上量:
        端块余量 `m = (导轨净长 − 滑块长 − 行程)/2`, 自检是 δ 跨度必须等于行程.
        **注意只有地轨的滑车在 full 链里被挪到了参考轨位**, 其余十根都还停在 CAD 位,
        所以量 raw 与量 full 只有地轨会不一致(静态件两份逐件相同, 可用来核对坐标系).
    这套推导有一条漂亮的自证: `axis_1z` 的几何解 [−52.4, 547.4] 与控制侧 PLC 限位
    [−50, 550] 是两条互不相干的证据链, 吻合到 2.4 mm.

35. **动作页的拖拽曾会随缩放翻向, 用它"实拖判定"出来的 `sign` 一律不可信.**
    2026-08-05 用户报"5Z 缩小时上下拖动正常, 放大后方向变反"与"缩放影响 6X 跟手感".
    病根在 `AxisDragController` 用**两条异面直线的最近点**闭式解求拖拽量, 两处硬伤:
    (a) 它跟的是**轴线**而不是抓取点, 而滑车零件从不正好骑在枢轴上 —— 增益正比于
        "相机↔轴线距离", 推近就塌缩. 实测同一次 20 mm 的拖拽在 22.2 m 处得 20.1 mm、
        在 minDistance(0.222 m)处得 29.3 mm, 枢轴偏离 1 m 时到 98.9 mm(**5 倍**);
    (b) 解含 `1/(1−(d·rd)²)`, 射线近平行于轴时发散, 旧代码用 `PARALLEL_EPS` 硬切到
        另一套"**1 米探针** + NDC 位移"的估计器 —— 那根探针近距时会落到眼平面之后,
        `project()` 除以负 w 把 NDC 整体镜像, **方向直接翻 180°**. 实测俯视 12° 时
        22.2/4.23/1.0/0.5 m 都给 +20 mm, 到 0.3/0.222 m 变成 −27.1/−26.1 mm.
        还有一条 `s0` 播种坑: `_paramAt` 的退化分支读 `drag.s0 ?? 0`, 而它正是用来给
        `s0` 赋值的, 此刻还是 `null` → 静默按 0 播种, 之后切回闭式分支会瞬间跳数百 mm
        (正视轴线时实测被甩到 4233 mm = 相机距离的毫米数).
    修法是换成**拖拽平面投影**(three.js `TransformControls` 同法): 过抓取点、含轴向、
    法向最正对相机的那张平面, 与指针射线求交后投影到轴向. 无放大项、无第二套估计器、
    无 NDC 探针, 且增益天然是"抓哪点哪点跟手". 近平行姿态(|n| < 0.15)**明确拒动并回报
    `blocked`** 由 HUD 提示, 不再静默乱走.
    **这不是手感问题**: `AXIS_ZERO_CALIBRATION.md` 七步法第 2 步就是"jog 看虚拟动向定
    sign", 于是 `axis_3y`/`axis_5z` 在 2026-08-02 被写进了两个由翻向拖拽判出来的 sign,
    还留了"与真机反向, 取反"的注释误导后人. 回归测在
    `web/tests/three-d/axisDrag.test.js`(三档相机距离 × 三个轴向 × 俯视角, 判据是
    "从 `screenOf(抓取点)` 拖到 `screenOf(抓取点 + 轴向·Δ)` 应恰好走 Δ", 与透视无关).
    **⚠ 2026-08-05 那轮清理只改了 `axis_4x` / `axis_3y` 的注释, 漏了 `axis_5z`** ——
    它一直带着"实拖判定与真机反向, 取反为 +1"和由它判出来的 `sign: +1`, 直到 2026-08-06
    用户报"实时页点样针明显靠上"才查出来. 已订正为 `sign: -1` + `zero_offset_mm: +48.5`
    (幅值不动, 只翻符号), 依据是 **PLC 源码**而不是任何观感: `A50_absorb_吸收液体` 里
    `fAbsTarget:=0` 是抬针、`:=position[2]`(46.5) 是下探, 且 4X 门禁写着"仅5Z**抬起**<3时放开4X"
    ⇒ 控制侧 mm 越大越低, 而模型轴向 [0,1,0] 朝上, 故 sign 必为 −1.
    **两个错误在 mm=0 处恰好抵消**(±48.5 各自都算出 +48.5), 再加上 5Z 是 11 根轴里唯一没有
    flat `Sampling_5Z_ActPos` 的一根(永远收不到非零遥测、恒停 mm=0), 于是静态画面完全看不出来
    —— 这类"成对错误互相掩盖"只能靠判据抓, 现已锁进
    `verify_sample_plates.check_needle_travel`(下探位针尖须落孔内、抬起位须高过板顶;
    拿旧值实测确实判红: 下探算出 171.51, 比板顶还高 53mm).

36. **`rig_map.yaml` 有第二个写入方, 长任务里改它之前必须重读.**
    前端指认模式经 18080 直写该文件(`runtime/three_d_authoring.py` 把它登记为可写),
    并行会话会互相覆盖. 2026-08-05 本会话就撞上了: 开工时读到的 `actuators:` 段只有
    5 条, 中途再看已被另一方补进 `col_extend`/`col_lift`/`col_press` 三条(共 +133 行),
    行号整体后移, 早先记下的行号全部失效. 症状是 Edit 工具提示"file had been modified
    on disk". 对策: 大段编辑前重新 grep 定位锚点, 别信上一轮的行号; 发现别人的成果先
    读懂再决定要不要动, 不要按自己的计划盲目覆盖.

37. **凡"由 X 推出 Y"的注释, 改 X 时必须回头复核 Y —— 尤其 X 当时是占位值.**
    2026-08-05 实锤: `axis_7y.sign` 写着"+1 由几何佐证: 滑块只能往 −X 走, 而唯一示教点
    −20 是负值, 取 −1 会要求 δ=+20 的正向行程". 该论证**隐含 `zero_offset = 0`**, 当时
    确实是占位 0; 后来零点改成 40、又改成 56, 论证没人回头看. 而"滑块只能往 −X 走"
    只推得出 `δ ≤ 0`, 推不出 `sign` —— sign=−1 时它等价于 `mm ≥ zero_offset`, 一样成立.
    结果: 三维里点样座朝反方向走 76 mm, `verify_plate_seats` 退出 1(偏 40.8 mm), 而
    那条失败提示又照着同一个错前提, 把病因写成"几何欠账, 留给现场卷尺" —— **错误结论
    被写进注释和两份文档, 反过来给下一个人当依据**, 差点就此定案.
    两条对策: (a) 改标定三元组里任何一个, 都要把该轴条目的注释整段重读一遍;
    (b) 判据脚本的失败提示里**不要写死"已知病因"**, 写"先查什么"——
    `verify_plate_seats` 现在的 (b) 分支就改成了"先怀疑 sign/zero_offset, 跑 --solve 比对".
    **2026-08-06 又抓到同一家族的两例, 都在 axis_4x 一条条目里:**
    (c) 那段注释自己推导出 `zero = 79.85`, 并且明写"差值只写注释, **不写进 zero_offset**",
        而 `zero_offset_mm` 恰恰就写着那个"差值" 156.85 —— **注释与值直接矛盾, 存活了一整周**;
    (d) 同条目另一句"取 −1 则上界只剩 22.5, 覆盖不了 50, 故反证 sign=+1 是对的",
        隐含**把 zero_offset 按住不动只翻 sign**; 两个一起翻则窗口照样够 —— 与 (a) 同型.
    ⇒ 复核标定三元组时, 把注释里每一句"由…可证"都当成待验命题, 逐句问"它假设了什么没动".

38. **装配台"会被删掉"的红色由管线裁决, 浏览器不许自己再算一遍.**
    2026-08-05 定位: 那套红色原本是 `blender_clean.prune` 的浏览器再实现
    (`workbench/pruneEval.js`), 与管线漂移出四类错判 —— (a) 拼音别名表覆盖不同,
    管线用 pypinyin 现算模型里每个中文名, 浏览器只能查 309 行的 `names.csv`
    (整表仅 1 条含"螺"), 于是 `keep_patterns` 的 `zhi_shi_deng` 永远命不中;
    (b) 尺寸口径不同, 管线取零件自身 `obj.dimensions`, 浏览器取子树**世界** AABB,
    旋转件世界盒恒偏大而漏红; (c) 管线在 prune **之后**才造的合成零件(注射泵指示灯
    由"注射泵风格化"生成、塔灯三段由 `split_tower` 生成)根本没经过删减, 却被浏览器
    套上 6mm 阈值判死 —— 用户看到的就是三颗指示灯常年顶着红色; (d) `region_delete`
    是**面级**删除, 节点粒度表达不了"只删线不删电机", 电机上那截注定被删的模制线缆
    一直是白的(点样水平模组 CFG4-L10-100 一案).
    现在收口成: `prune()` 拆出 `prune_verdict()` 只判不删, 正式删减与 raw 阶段共用它;
    raw 阶段另跑 `region_split()` 把面岛**分离**成 `<节点名>__REGION_DELETE` 的独立
    对象(几何总量与外观不变), 裁决落成 `work/prune_preview.json`, 浏览器只展开名字。
    两个必须记住的点: (a) 手改 `prune_list.yaml` 的**规则档**后要重跑 `raw-swap + raw`
    (约 2 分钟)标红才跟得上, 没跟上时页面顶栏会挂"预览为近似"告警 —— 与片段陈旧检测
    同一约定, **缺戳一律不许判绿**; 只改 `explicit_*` 名单不用重跑(那几档页面实时算,
    基线里 `reason=explicit` 的条目会被刻意跳过, 否则取消标记后红色退不掉);
    (b) 基线的戳用 FNV-1a 而不是 SHA-256 —— 装配台常从局域网 IP 走 http 打开, 那不是
    安全上下文, `crypto.subtle` 在那里直接是 `undefined`, 用它等于让告警条永久挂着.

39. **演示台播的是"精编译片段", 面板里的入参改了不影响播放.**
    2026-08-06 用户报"改 `吸样盘位号`/`吸样孔位` 完全没反应"。不是 bug: 正式片段的入参在
    **编译期**就烘进了 `clips/flow.*.yaml`(`operation.inputs` 与各步的 `axis.to_mm`),
    播放器只读片段。面板右下那行小字已写明, 但它太容易被忽略 —— 要换参数只能重编译
    (`sync_ptlc_robot.py --plates --flows`, 全量约 10.6 分钟)。
    排查"演示里位置不对"时, **先看片段里烘的是什么**, 别对着面板猜。

40. **控制侧的 mm 不一定是物理 mm —— `axis_4x` 上 1 控制 mm = 2 物理 mm.**
    2026-08-06 卡尺定案(轴读 11.28mm 实走 ≈22.6mm)。病根是那根轴的标度把每转行程配成了
    实际的一半; 它**不是 SV660N 伺服**(整机 8 台驱动器却有 11 根轴), 是自制同步带 +
    42CM08 步进, 标度另配也就配错了。三维用 `axes[].scaleMm` 补偿, 换算的唯一口径是
    `MachineStateDriver.axisUnitPerMm = sign × scaleMm × mmToUnit`
    (`setAxisMm` 乘它、`AxisDragController` 除它, **必须同源**, 各写一遍就会差一倍)。
    三条连带口径, 改增益时一起看: `rangeMm`/控制侧 limits 是**控制侧 mm**,
    `strokeMm` 与几何 δ 是**物理 mm**, `check_axis_limits` 要乘回增益再比。
    **⚠ 这是临时补偿**, 4X/5Z 换伺服后作废; **5Z 的标度至今未验**(它的
    `diActPosition` 三次实读都恰好是 0, 除不出比值)。全部细节与退役清单见
    `docs/上样4X_5Z临时标度增益_换伺服后作废_20260806.md`。
    附一个好用的手法: 轴的 inc/mm 可由 `IoConfig_Globals.<轴名>` 的
    `diActPosition`/`fActPosition` **两点相减**直接反解(免疫零点偏移), 各伺服轴解出来
    恰是 `2²³ / 导程`, 与型号里的 L5/L10 逐项吻合 —— 这条能在不动机器的前提下体检标度。

## 命名契约(Blender ↔ manifest ↔ 前端加载器)

```
MACHINE/
  ST_<STATION>/                SAMPLING | DEVELOP | COLLECT | PHOTO |
                               FEEDLIFT | PUMP | RAIL | STAGINGA | FRAME
    STATIC                     合并后的静态几何
    LIGHT_STATUS               自发光状态灯(唯一参与辉光的物体)
    AXIS_<ID>/                 ID = manifest axes[].id 全大写 —— 节点名是 AXIS_AXIS_4X
                               (blender_clean 按 f"AXIS_{axis_id.upper()}" 拼, id 本身含 axis_ 前缀)
      CARRIAGE/                运动组; 枢轴位于零位, 局部轴正方向 = 位置增大方向
        AXIS_<ID>/CARRIAGE     叠轴嵌套, 如 AXIS_AXIS_4X/CARRIAGE/AXIS_AXIS_5Z/CARRIAGE
    TANK_<n>/ LIQUID | LID     仅展开工位
ST_RAIL/AXIS_AXIS_11Y/CARRIAGE/           ← 官方臂(ST_ROBOT)与 SOCKET_ROBOT_BASE 挂在此下
```

前端 `loadModel.js` 的 `buildNodeIndex` 会把上述层级展开成 `"A/B/C"` 形式的索引键,
`device-manifest.json` 里的 `glbNode` 字段就是这个键.

## 性能预算(`05_report.py` 硬门禁)

| 指标 | 上限 | 说明 |
|---|---|---|
| 文件体积 | 25 MB | 影响首屏加载 |
| 绘制调用(图元数) | 500 | 最先突破的一项 |
| 三角形数 | 3,000,000 | 影响 GPU 与显存 |
| 语义命名占比 | ≥ 50%(警告项) | 低于此说明名称传播出了问题 |

超预算时的调节手段, 按性价比排序:
1. 扩大 `prune_list.yaml` 的删减范围(紧固件/拖链/供应商杂件收益最高)
2. 提高 `04_optimize.mjs` 的 `--simplify` 力度
3. 调大 `pipeline.yaml` 的 `convert.tol_linear`(重跑 02, 耗时约 11 分钟)

## 管线运行顺序

```bash
cd E:/eit_lab/pTLC_platformUI/eit_ptlc/three_d/pipeline
python 01_fix_step_names.py                 # STEP 改名 + 装配实例名回填(约 8s)
python 02_convert_step.py                   # STEP -> GLB(整机约 11 分钟)
python inspect_glb.py ../work/xxx.raw.glb   # 核对命名质量
python 03_clean_model.py --stage minimal    # Blender 删减/赋材质/合并
node 04_optimize.mjs                        # gltf-transform 压缩
python 05_report.py                         # 预算门禁
```

上位机前端与后端:
```powershell
cd E:/eit_lab/pTLC_platformUI/eit_ptlc/web
npm run build
cd E:/eit_lab/pTLC_platformUI
& "C:/ProgramData/miniforge3/python.exe" eit_ptlc/main.py --no-browser
# 浏览器打开 http://localhost:18080/3d/live
```

## 与上位机的关系

- 上位机仓库: `E:/eit_lab/pTLC_platformUI/eit_ptlc`(FastAPI + Vue3 SPA)
- 实时数据: WebSocket `/api/ws/events`, 1 Hz 遥测; 机械臂已含 `joint[6]`,
  展开工位已含 `Tank_State[8]`
- 动作执行: `GET /api/actions` 拿目录, `POST /api/actions/{name}/run` 执行,
  有 RUN/DEBUG 模式门禁
- 仿真模式: `C:/ProgramData/miniforge3/python.exe eit_ptlc/main.py --no-browser` 启动 mock PLC + 仿真机械臂, 开发全程无需真机
- 三维界面、运行时适配、资源、管线、文档和工具都在上位机仓库维护, 不存在独立三维应用

## 里程碑

M0~M4 均已完成, 详见 [M0-完成记录.md](M0-完成记录.md) 与 [M1-M4-完成记录.md](M1-M4-完成记录.md).

- **M0** 管线打通: STEP → 浏览器里可旋转的整机 ✔
- **M1** 语义模型: rig_map 工位重组 + 8 展缸液面 + 11 状态灯 + device-manifest ✔
- **M2** 实时绑定: 上位机 ActPos 补丁 + TwinFeed/interp/TwinBindings ✔
- **M3** 交互: 拾取选中 + 外罩透视 + 工位面板 + 动作表单 + 时间线回放 ✔
- **M4** 集成: 上位机 SPA 的五个 `/3d/*` 工作台 ✔

### 下一步(按性价比排序)

1. **补全其余 10 条运动轴的装配与零点标定.** 当前只有地轨完成. 逐轴做法: 在 raw 模型/
   源 CAD 里确认随轴移动的零件组, 填进 `rig_map.yaml` 对应轴的 `carriage_members` 并置
   `rigged: true`, 重跑 `03 → gen_twin_manifest → 04`; 然后用 `/3d/calib` 的
   AxisDebugPanel 离线 jog 核对随动组, 现场按 `docs/AXIS_ZERO_CALIBRATION.md` 的
   七步法标零(live 微调 zero_offset_mm/sign, 导出 YAML 回填 rig_map). 绑定时必须
   同步把 `range_mm` 扩到控制侧限位并集(gen_twin_manifest 有校验警告).
2. **机械臂关节驱动.** 按 Dobot 官方 CR5 的 URDF 重建关节链导出为独立 GLB,
   挂到 `ST_RAIL/AXIS_11Y/CARRIAGE` 下. 遥测侧的 `joint[6]` 已在 TwinFeed 就位.
3. **用 sw-mcp 按模块重导 AP214.** 现有模型是 2026-02 的旧 AP203 导出, 落后约半年且无颜色.
4. **pose 事件 5 Hz**(见"上位机补丁"一节的 Phase 2), 仅当 1 Hz + 插值的观感不够时才做.

## 用户的角色

用户**只做审查**, 不亲自操作 SolidWorks 与 Blender —— 二者都通过 MCP 由 AI 驱动.
需要用户介入的只有四类节点: 效果拍板、rig_map 归属确认、审美取向、代码审查.
