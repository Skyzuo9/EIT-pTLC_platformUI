/**
 * 功能: 效果预览沙盒的全部可调参数集中地.
 *
 * 用户调参只看这一个文件: 每项带中文注释与单位, 改完刷新即生效.
 * 控制面板的滑杆由 PARAM_DEFS / DISPLAY_DEFS 声明自动生成(面板与配置永不漂移);
 * URL 里任何 `cfg.<路径>=<数值>` 参数会覆写对应项, 面板滑杆改动也会自动写回 URL.
 *
 * 第四轮(2026-08-06)按用户反馈: 状态圆点删除; 开场换"幽灵整机→由左往右实体化"扫场;
 * 聚焦/巡检改每工位定制视角(stationViews); 新增开关门(doors); 页面套仿正式应用外壳.
 * 第三轮遗产: hover 白卡 + 聚焦"幽灵换材质"隔离(周围半透明、聚焦对象保持实体).
 */

/** 全部默认参数. 长度单位米, 时间单位秒, 角度单位度, 像素值标 px */
export const FX_DEFAULTS = {
  cards: {
    anchorLift: 0.05,     // 固定详情卡 3D 锚点在工位顶部带之上的抬高量(米)
    anchorBand: 0.28,     // 锚点"顶部带"比例: 只用顶面落在最高点向下这一带内的网格定 xz
    anchorNudge: {},      // 每工位锚点手调偏移(世界米制), 如 { DEVELOP: [0, 0.02, 0] }
    pinnedRisePx: 18,     // 固定详情卡底边在锚点投影之上的抬升(px)
  },
  hover: {
    offsetX: 18,          // 悬浮白卡相对光标的偏移(px)
    offsetY: 20,
    throttleMs: 40,       // 悬停射线检测节流(毫秒)
  },
  focus: {
    isolation: 'ghost',   // 聚焦/巡检时对周围结构: ghost=幽灵半透明(默认) hide=隐藏 off=不处理
    ghostOpacity: 0.1,    // 幽灵材质不透明度
  },
  display: {
    // 数值基准 = 正式页 Environment.RIG x displaySettings 默认(可一比一搬回正式页);
    // 曝光问题的实测结论: 过曝对 key 强敏感、对 env 几乎不敏感 —— 调亮暗先动 brightness/key
    brightness: 1.1,      // 总亮度系数(乘 4 盏灯 + 环境强度) —— 主曝光通道
    keyIntensity: 0.7,    // 主光
    hemiIntensity: 0.45,  // 半球光
    fillIntensity: 0.28,  // 补光
    rimIntensity: 0.15,   // 轮廓光
    envIntensity: 0.85,   // 环境贴图强度(影棚灯板)
    bgIntensity: 1.0,     // 背景亮度(渐变贴图), 雾色随之下压
    shadowIntensity: 0.8, // 阴影浓度(着色期 uniform)
    exposure: 1.0,        // renderer.toneMappingExposure(沙盒专用旋钮, 正式页无此项)
  },
  tour: {
    dwellS: 4,            // 巡检模式每工位停留时长(秒, 不含飞行)
    flyS: 2.0,            // 巡检模式给飞行动画预留的时长(秒)
    route: '',            // 巡检路线: 空串=自动按世界 X 左→右全工位; 或逗号分隔工位 id 串
  },
  intro: {
    // 开场 v3(第五轮): 幽灵整机**自上而下逐像素**实体化(双层裁剪面, 非逐零件硬切) +
    // 相机环绕推近(转到位=实体化完成) + 科技蓝扫描平面跟随分解线.
    // 总时长 = durS + tailS, 默认 3.2s —— 与 main.freezeAt 的快进窗口绑定, 改长必须同步!
    durS: 2.8,            // 分解线顶到底 = 相机环绕到位 的共同时长
    tailS: 0.4,           // 扫完(平面淡出)后再静置多少秒收尾(还原输入)
    azFromDeg: -130,      // 相机起始方位角偏移(度, 相对终点 iso 机位; 环绕途中掠过正面)
    elFromDeg: 34,        // 相机起始仰角(度; 俯瞰进场, 落回 iso 仰角≈24°)
    camStartScale: 1.35,  // 起始距离 = 标准 front 机位距离 x 该系数
    planeScale: 1.14,     // 扫描平面相对整机脚印的放大倍率
    planeOpacity: 0.42,   // 扫描平面不透明度(加色混合, 配辉光)
  },
  /**
   * 每工位定制聚焦/巡检视角(用户第四轮定夺: 不再自动取景, 要"完整看到模块+看到正面").
   * azDeg: 方位角(0=+Z 整机正面, 正角向 +X 右端转) / elDeg: 仰角 /
   * fill: **距离余量倍率**(1=模块恰好贴满画面边, 越大离得越远 —— 取景距离按包围盒
   * 8 角点精确解, 数学上保证完整入画) / radiusM: >0 时改用定半径球拟合(米;
   * 机械臂只框臂体不框整条地轨用).
   * 全部具名标量 —— URL 可逐键覆写(cfg.stationViews.RACK.azDeg=…), 面板"固化机位"
   * 按钮会把手调好的机位写回这里对应的三键.
   */
  stationViews: {
    RACK: { azDeg: -35, elDeg: 18, fill: 1.12, radiusM: 0 },        // 最左端, 从左前方看端头
    DEVELOP: { azDeg: -25, elDeg: 18, fill: 1.08, radiusM: 0 },     // 左区双塔, 偏左显纵深
    PUMP: { azDeg: -15, elDeg: 16, fill: 1.1, radiusM: 0 },         // 中左, 近正面微偏
    TOOLING: { azDeg: -12, elDeg: 18, fill: 1.1, radiusM: 0 },      // 与泵站相邻, 同带微偏
    ROBOT: { azDeg: 8, elDeg: 20, fill: 0.95, radiusM: 0.85 },      // 锚点跟臂+定半径框臂体带上下文
    VISION: { azDeg: 6, elDeg: 12, fill: 1.06, radiusM: 0 },        // 埋台下, 浅仰角借幽灵透视
    COLLECT: { azDeg: 10, elDeg: 16, fill: 1.1, radiusM: 0 },       // 中右, 近正面微右
    STAGINGA: { azDeg: 12, elDeg: 18, fill: 1.08, radiusM: 0 },     // 小件, 余量收一点放大主体
    FEEDLIFT: { azDeg: 22, elDeg: 18, fill: 1.08, radiusM: 0 },     // 右区, 明确右偏
    PHOTOSCRAPE: { azDeg: 28, elDeg: 18, fill: 1.08, radiusM: 0 },  // 更靠右端, 偏角加大
    SAMPLING: { azDeg: 35, elDeg: 18, fill: 1.08, radiusM: 0 },     // 最右端, 与料架镜像
  },
  /**
   * 可开门 —— 全机 8 扇合页门(前后长面各 3 扇 + 左端面对开 2 扇).
   *
   * nodes: 门体节点路径(逗号分隔, 多件=同一扇门刚性同转, 如上料门的钣金框+亚克力窗);
   * hinge: 铰链竖边取门世界盒的哪条边(minX/maxX/minZ/maxZ); openDeg: 开度(度);
   * sign: 开向(从 +Y 俯视逆时针为 +); pair: 对开门的另一扇(点一扇两扇同开).
   *
   * ⚠ hinge/sign **不是可调口味, 是几何事实**, 改之前先看证据 ——
   * 铰链边由 CAD 合页件 `AKQ41-G-Z-6065_*`(每扇 2 只, 骑在铰链那条竖边上)定,
   * 把手 `XAD51-A100-*` 永远在对边(=自由边). 前面(Z≈+0.75)与后面(Z≈−0.77)各有
   * 3 根合页立柱 X = −1.21 / +0.27 / +1.23, 左端面(X≈−1.30)2 根 Z = −0.68 / +0.67.
   * sign 由"自由边必须朝机外走"定: align 组已把 hinge 局部轴对齐世界轴, 故
   * hinge.rotation.y 就是绕世界 +Y 转, (x,z) → (x cosθ + z sinθ, −x sinθ + z cosθ);
   * 代入各扇的"铰链→自由边"方向解出下表. 前面朝 +Z 开, 后面朝 −Z, 左端朝 −X.
   *
   * 名带"固定门板"的 4 扇一度被判为"按图纸不可开"而漏做 —— 那是误判, 它们同样
   * 带合页带把手. 它们要能动, 前提是在 material_semantics.yaml 的 part_isolate 里
   * (否则会被并进静态合并块, 整块只能一起动).
   *
   * 每扇门的 nodes = 门板 + **骑在门上的五金**(把手 XAD51 + 合页门叶组 DOOR_HINGE_*).
   * 漏了五金门照转, 但把手会明晃晃悬在关门位置(2026-08-09 用户报的 bug).
   * 全机普查过: 每扇门骑着且仅骑着这 3 件, 没有别的遗漏件.
   * · 把手节点名 = CAD 原名, 8 只各自独立;
   * · 合页组节点名是**管线造的**: 16 片门叶在 CAD 里同名, 由
   *   blender_clean.rename_door_hinge_leaves() 按几何改成 DOOR_HINGE_<门键>, 再由
   *   part_isolate 孤立; 同扇两片同名 -> 同材质 -> 合并成 STATIC_MAT_SOLO_DOOR_HINGE_<门键>.
   * **门板必须排在 nodes 第一位** —— doors.js 拿 nodes[0].parent 当 align 枢轴的宿主.
   */
  doors: {
    animS: 0.9,           // 单扇门开/合动画时长(秒)
    // 左端面对开门(把手在中缝 Z≈0 两侧, 铰链在外沿)
    sideL1: { nodes: 'ST_FRAME/机架总装-1/侧门-1,ST_FRAME/机架总装-1/XAD51-A100-6,ST_FRAME/STATIC_MAT_SOLO_DOOR_HINGE_sideL1', hinge: 'maxZ', openDeg: 110, sign: 1, pair: 'sideL2' },
    sideL2: { nodes: 'ST_FRAME/机架总装-1/侧门-2,ST_FRAME/机架总装-1/XAD51-A100-7,ST_FRAME/STATIC_MAT_SOLO_DOOR_HINGE_sideL2', hinge: 'minZ', openDeg: 110, sign: -1, pair: 'sideL1' },
    // 前上料门 = 钣金框 + 内嵌亚克力观察窗两件一体(单扇, 无配对)
    feed: { nodes: 'ST_FRAME/机架总装-1/上料门板-1,ST_FRAME/机架总装-1/门板-5,ST_FRAME/机架总装-1/XAD51-A100-1,ST_FRAME/STATIC_MAT_SOLO_DOOR_HINGE_feed', hinge: 'maxX', openDeg: 100, sign: 1 },
    // 后面同位置的对面门(单扇, 无配对)
    back: { nodes: 'ST_FRAME/机架总装-1/侧门板-1,ST_FRAME/机架总装-1/XAD51-A100-8,ST_FRAME/STATIC_MAT_SOLO_DOOR_HINGE_back', hinge: 'maxX', openDeg: 100, sign: -1 },
    // 前面左半对开门(把手相邻于中缝 X≈−0.473, 铰链在外沿 +0.27 / −1.21).
    // ⚠ openDeg 别跟着左端那对抄 110 —— 靠 feed 那侧的 L1 与 feed 的扫掠圆盘会打架:
    //   feed 铰链(1.226,0.730) 半径 0.878; L1 全开时门板线段离该铰链 100°→945mm(余 67mm)
    //   而 110°→902mm(余 24mm), 再扣门板半厚就只剩十几毫米, 两扇同开时会穿模. 后面镜像同理.
    frontL1: { nodes: 'ST_FRAME/机架总装-1/固定门板-5,ST_FRAME/机架总装-1/XAD51-A100-3,ST_FRAME/STATIC_MAT_SOLO_DOOR_HINGE_frontL1', hinge: 'maxX', openDeg: 100, sign: 1, pair: 'frontL2' },
    frontL2: { nodes: 'ST_FRAME/机架总装-1/固定门板-6,ST_FRAME/机架总装-1/XAD51-A100-2,ST_FRAME/STATIC_MAT_SOLO_DOOR_HINGE_frontL2', hinge: 'minX', openDeg: 100, sign: -1, pair: 'frontL1' },
    // 后面左半对开门(与前面镜像, 朝 −Z 开)
    backL1: { nodes: 'ST_FRAME/机架总装-1/固定门板-2,ST_FRAME/机架总装-1/XAD51-A100-5,ST_FRAME/STATIC_MAT_SOLO_DOOR_HINGE_backL1', hinge: 'maxX', openDeg: 100, sign: -1, pair: 'backL2' },
    backL2: { nodes: 'ST_FRAME/机架总装-1/固定门板-3,ST_FRAME/机架总装-1/XAD51-A100-4,ST_FRAME/STATIC_MAT_SOLO_DOOR_HINGE_backL2', hinge: 'minX', openDeg: 100, sign: 1, pair: 'backL1' },
  },
  postfx: {
    bloomIntensity: 1.6,  // 辉光强度(与正式页 Effects.js 同值起步; 流程片段的工艺灯用)
    bloomThreshold: 0.35, // 辉光亮度阈值(同正式页)
    bloomRadius: 0.62,    // 辉光半径(同正式页)
    vignetteOffset: 0.3,  // 暗角起始半径(同正式页)
    vignetteDarkness: 0.25, // 暗角强度(同正式页)
  },
  sim: {
    errorRecoverS: 10,    // 面板"注入故障"后自动自愈的秒数
  },
}

/**
 * 显示设置控件声明(范围/步长照正式页 DISPLAY_FIELDS): 面板"显示设置"段按它生成,
 * 改动即时经 stage.applyDisplay 生效. sandboxOnly 标注"正式页没有对应项"的旋钮.
 */
export const DISPLAY_DEFS = [
  { path: 'display.brightness', label: '总亮度', min: 0.3, max: 1.6, step: 0.05 },
  { path: 'display.keyIntensity', label: '主光', min: 0, max: 2.5, step: 0.05 },
  { path: 'display.hemiIntensity', label: '半球光', min: 0, max: 1.0, step: 0.02 },
  { path: 'display.fillIntensity', label: '补光', min: 0, max: 1.0, step: 0.02 },
  { path: 'display.rimIntensity', label: '轮廓光', min: 0, max: 1.5, step: 0.05 },
  { path: 'display.envIntensity', label: '反射强度', min: 0, max: 2.0, step: 0.05 },
  { path: 'display.bgIntensity', label: '背景亮度', min: 0.4, max: 1.3, step: 0.02 },
  { path: 'display.shadowIntensity', label: '阴影浓度', min: 0, max: 1, step: 0.02 },
  { path: 'display.exposure', label: '曝光', min: 0.5, max: 1.5, step: 0.02, sandboxOnly: true },
]

/** 特效参数滑杆声明(开场时长类不上滑杆 —— 与 freezeAt 窗口绑定, 改错会破截图定格) */
export const PARAM_DEFS = [
  { path: 'focus.ghostOpacity', label: '幽灵浓度', min: 0.02, max: 0.4, step: 0.01 },
  { path: 'cards.anchorLift', label: '锚点抬高', min: 0, max: 0.25, step: 0.005 },
  { path: 'cards.pinnedRisePx', label: '详情卡高度', min: 0, max: 120, step: 2 },
  { path: 'doors.animS', label: '开门时长', min: 0.3, max: 2, step: 0.1 },
  { path: 'postfx.bloomIntensity', label: '辉光强度', min: 0, max: 3.5, step: 0.1 },
]

/**
 * 功能: 按 "a.b.c" 路径读值.
 * @param {object} obj 目标对象
 * @param {string} path 点分路径
 * @returns {*} 值(不存在返回 undefined)
 */
export function getPath(obj, path) {
  let cur = obj
  for (const key of path.split('.')) {
    if (cur == null || typeof cur !== 'object') return undefined
    cur = cur[key]
  }
  return cur
}

/**
 * 功能: 按 "a.b.c" 路径写值(路径上的中间对象必须已存在 —— 防止 URL 拼错悄悄造出新键).
 * @param {object} obj 目标对象
 * @param {string} path 点分路径
 * @param {*} value 新值
 * @returns {boolean} 是否写入成功
 */
export function setPath(obj, path, value) {
  const keys = path.split('.')
  let cur = obj
  for (const key of keys.slice(0, -1)) {
    if (cur == null || typeof cur[key] !== 'object') return false
    cur = cur[key]
  }
  const last = keys[keys.length - 1]
  if (!(last in cur)) return false
  cur[last] = value
  return true
}

/**
 * 功能: 生成运行配置 = 深拷贝默认值 + URL `cfg.*` 覆写.
 * @param {URLSearchParams} [search] URL 查询参数
 * @returns {object} 可变的运行配置对象
 */
export function makeConfig(search) {
  const config = JSON.parse(JSON.stringify(FX_DEFAULTS))
  if (search) {
    for (const [key, raw] of search.entries()) {
      if (!key.startsWith('cfg.')) continue
      const num = Number(raw)
      const value = Number.isFinite(num) && raw !== '' ? num
        : raw === 'true' ? true : raw === 'false' ? false : raw
      setPath(config, key.slice(4), value)
    }
  }
  return config
}
