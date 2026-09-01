/**
 * 功能: 显示设置的纯状态机 —— 字段元数据、夹取、按主题分槽的覆盖存储与序列化.
 *
 * 设计约定:
 *   - 本模块**零依赖、不摸 window/three**(theme.js 顶层会摸 window.location, node --test
 *     直接 import 会崩), 一切环境依赖(storage/基准值)由调用方注入 —— 这也是它可以被
 *     node --test 直接单测的原因.
 *   - 存储的是**稀疏覆盖**而不是全量值: 没动过的字段永远跟随 RIG 基准, 以后再校
 *     默认值时不会被旧存档钉死; 动过的字段"钉住"正是用户意图.
 *   - **单槽**: 2026-08-05 起昼夜共用同一套观感参数(见 Environment.js 的 RIG), 滑块值
 *     也就共用一组. v1 曾按 dark/light 分槽 —— 那时两套光照差一个数量级, 共用会打架.
 */

/**
 * localStorage 键(v2: {version, overrides: 稀疏覆盖}).
 *
 * v1→v2 **不迁移**: v1 里存的是针对旧基准调的稀疏覆盖, 换不过来 —— 比如存着的 dark
 * keyIntensity 0.9 当年意思是"1.15 的 78%", 放到 0.7 的新基准上就变成 129%, 带过来只会
 * 在老浏览器上钉住一个谁也没选的外观。而本次的目的恰恰是"其他浏览器打开就是这个效果"。
 */
export const DISPLAY_KEY = 'ptlc.display.v2'
/** v1 的键: 只留名, 不读不删(供回滚) */
export const LEGACY_DISPLAY_V1_KEY = 'ptlc.display.v1'
/**
 * 更早的光照旋钮键: 已彻底退役, 现在谁都不读它。
 *
 * 它曾在"display 键不存在时"折算迁移一次。v2 一 bump, 那个条件在**每个**老浏览器上都
 * 成立, 于是还留着这个远古键的机器会把 brightness/envIntensity 重新迁进崭新的 v2 槽,
 * 恰好在本次要统一的机器上重新钉出一个非默认外观 —— 所以迁移分支连同它一起废掉。
 * 键名保留仅为回滚时能找到数据。
 */
export const LEGACY_LIGHTING_KEY = 'ptlc.lighting.v1'
/** 背景场景是全局偏好, 不跟随 dark/light 分槽 */
export const BACKGROUND_KEY = 'ptlc.background.v1'
export const DEFAULT_BACKGROUND_SCENE = 'default'
export const BACKGROUND_SCENES = Object.freeze(['default', 'laboratory'])

/**
 * 字段元数据: 面板渲染顺序、夹取范围、档位约束与测量方式的唯一来源.
 *   group: 'light' 光源 | 'shadow' 阴影 | 'fx' 效果 | 'scene' 场景
 *   tierKey: 画质档位里的开关名 —— 档位不允许时该项置灰(有效状态=档位允许 且 用户开)
 *   invalidatesShadows: 改动后需要重渲阴影贴图(仅主光角度与阴影开关; 浓度/柔度是
 *                       着色期 uniform, 不进贴图)
 *   measurable: 'passive' 扳开关即自动实测负载增量 | 'driven' 需主动测量(按需阴影
 *               静止时零开销, 被动测不到)
 *   dependsOn: 依赖的开关字段, 其为关时本项置灰
 */
export const DISPLAY_FIELDS = [
  // -- 光源 ---------------------------------------------------------------
  // 每盏灯一个独立开关(默认开): 有的光源在特定视角/材质上会产生刺眼高光,
  // 开关比把强度拖到 0 语义更明确, 且关掉后原强度值仍被记住
  { key: 'brightness', group: 'light', label: '总亮度', type: 'range', min: 0.3, max: 1.6, step: 0.05 },
  { key: 'keyEnabled', group: 'light', label: '主光', type: 'toggle', invalidatesShadows: true },
  { key: 'keyIntensity', group: 'light', label: '主光强度', type: 'range', min: 0, max: 2.5, step: 0.05, dependsOn: 'keyEnabled' },
  { key: 'keyAzimuthDeg', group: 'light', label: '主光方位', type: 'range', min: -180, max: 180, step: 1, unit: '°', invalidatesShadows: true, dependsOn: 'keyEnabled' },
  { key: 'keyElevationDeg', group: 'light', label: '主光仰角', type: 'range', min: 15, max: 85, step: 1, unit: '°', invalidatesShadows: true, dependsOn: 'keyEnabled' },
  { key: 'fillEnabled', group: 'light', label: '补光', type: 'toggle' },
  { key: 'fillIntensity', group: 'light', label: '补光强度', type: 'range', min: 0, max: 1.0, step: 0.02, dependsOn: 'fillEnabled' },
  { key: 'rimEnabled', group: 'light', label: '轮廓光', type: 'toggle' },
  { key: 'rimIntensity', group: 'light', label: '轮廓强度', type: 'range', min: 0, max: 1.5, step: 0.05, dependsOn: 'rimEnabled' },
  { key: 'hemiEnabled', group: 'light', label: '半球光', type: 'toggle' },
  { key: 'hemiIntensity', group: 'light', label: '半球强度', type: 'range', min: 0, max: 1.0, step: 0.02, dependsOn: 'hemiEnabled' },
  { key: 'envEnabled', group: 'light', label: '环境反射', type: 'toggle' },
  { key: 'envIntensity', group: 'light', label: '反射强度', type: 'range', min: 0, max: 2.0, step: 0.05, dependsOn: 'envEnabled' },
  // -- 阴影 ---------------------------------------------------------------
  { key: 'shadowsEnabled', group: 'shadow', label: '实时阴影', type: 'toggle', tierKey: 'shadows', invalidatesShadows: true, measurable: 'driven' },
  { key: 'shadowIntensity', group: 'shadow', label: '阴影浓度', type: 'range', min: 0, max: 1, step: 0.02, tierKey: 'shadows', dependsOn: 'shadowsEnabled' },
  { key: 'shadowRadius', group: 'shadow', label: '阴影柔度', type: 'range', min: 0, max: 16, step: 0.5, tierKey: 'shadows', dependsOn: 'shadowsEnabled' },
  { key: 'contactStrength', group: 'shadow', label: '接触影浓度', type: 'range', min: 0, max: 0.6, step: 0.02 },
  // -- 效果 ---------------------------------------------------------------
  { key: 'ssaoEnabled', group: 'fx', label: '环境光遮蔽', type: 'toggle', tierKey: 'ssao', measurable: 'passive' },
  { key: 'ssaoIntensity', group: 'fx', label: 'AO 强度', type: 'range', min: 0, max: 4, step: 0.1, tierKey: 'ssao', dependsOn: 'ssaoEnabled' },
  { key: 'bloomEnabled', group: 'fx', label: '状态灯辉光', type: 'toggle', tierKey: 'bloom', measurable: 'passive' },
  { key: 'vignetteEnabled', group: 'fx', label: '暗角', type: 'toggle', tierKey: 'vignette', measurable: 'passive' },
  { key: 'vignetteDarkness', group: 'fx', label: '暗角强度', type: 'range', min: 0, max: 0.6, step: 0.02, tierKey: 'vignette', dependsOn: 'vignetteEnabled' },
  { key: 'reflectionEnabled', group: 'fx', label: '地面倒影', type: 'toggle', tierKey: 'reflection', measurable: 'passive' },
  // -- 场景 ---------------------------------------------------------------
  {
    key: 'backgroundScene',
    group: 'scene',
    label: '背景',
    type: 'select',
    scope: 'global',
    invalidatesShadows: true,
    options: [
      { value: 'default', label: '默认场景' },
      { value: 'laboratory', label: '实验室' },
    ],
  },
  { key: 'bgIntensity', group: 'scene', label: '背景亮度', type: 'range', min: 0.4, max: 1.3, step: 0.02 },
  { key: 'fogEnabled', group: 'scene', label: '远景雾', type: 'toggle', measurable: 'passive' },
  {
    key: 'gridVisible',
    group: 'scene',
    label: '地面网格',
    type: 'toggle',
    measurable: 'passive',
  },
]

/** key -> 字段元数据 */
export const FIELD_BY_KEY = new Map(DISPLAY_FIELDS.map((field) => [field.key, field]))

/**
 * 功能: 空的设置状态(无任何覆盖).
 * @returns {{version: number, overrides: object}} 状态
 */
export function defaultState() {
  return { version: 2, overrides: {} }
}

/**
 * 功能: 按字段元数据夹取一个值. 未知字段或无法归一的值返回 null(调用方按"无效"处理).
 * @param {string} key 字段名
 * @param {*} value 输入值
 * @returns {number|boolean|string|null} 归一后的值
 */
export function clampValue(key, value) {
  const field = FIELD_BY_KEY.get(key)
  if (!field) return null
  if (field.type === 'toggle') {
    if (typeof value !== 'boolean' && value !== 0 && value !== 1) return null
    return Boolean(value)
  }
  if (field.type === 'select') {
    const candidate = String(value)
    return field.options?.some((option) => option.value === candidate) ? candidate : null
  }
  const num = Number(value)
  if (!Number.isFinite(num)) return null
  return Math.min(field.max, Math.max(field.min, num))
}

/**
 * 功能: 写入/删除一个覆盖值(单槽, 昼夜共用).
 * @param {object} state 设置状态(就地修改)
 * @param {string} key 字段名
 * @param {*} value 新值; null/undefined 表示删除该覆盖(回到基准)
 * @returns {number|boolean|null} 实际写入的值(删除或无效时为 null)
 */
export function setOverride(state, key, value) {
  const slot = state?.overrides
  if (!slot || !FIELD_BY_KEY.has(key)) return null
  if (value === null || value === undefined) {
    delete slot[key]
    return null
  }
  const clamped = clampValue(key, value)
  if (clamped === null) {
    delete slot[key]
    return null
  }
  slot[key] = clamped
  return clamped
}

/**
 * 功能: 取覆盖副本.
 * @param {object} state 设置状态
 * @returns {object} 稀疏覆盖(副本)
 */
export function overridesFor(state) {
  return { ...(state?.overrides || {}) }
}

/**
 * 功能: 基准 ⊕ 覆盖 合成全量生效值.
 * @param {object} baseline 全量基准(来自 RIG 等派生)
 * @param {object} overrides 稀疏覆盖
 * @returns {object} 全量有效设置
 */
export function effectiveSettings(baseline, overrides) {
  return { ...baseline, ...(overrides || {}) }
}

/**
 * 功能: 从存储读设置状态(v2 单槽); 缺失或异常一律回默认.
 *
 * **不从任何旧键迁移**(v1 分槽覆盖 / 更远古的 lighting 旋钮): 旧值是按旧基准调的相对量,
 * 换算过来只会在老浏览器上钉住一个谁也没选的外观, 与本次"统一默认外观"的目的相反.
 * 旧键都**不删除**, 供回滚. 详见 DISPLAY_KEY / LEGACY_LIGHTING_KEY 的注释.
 *
 * @param {{getItem: Function}} storage localStorage 或注入的假对象
 * @returns {{version: number, overrides: object}} 设置状态
 */
export function loadDisplayState(storage) {
  const state = defaultState()
  try {
    const raw = storage?.getItem?.(DISPLAY_KEY)
    if (!raw) return state
    const parsed = JSON.parse(raw)
    const slot = parsed?.overrides
    if (!slot || typeof slot !== 'object') return state
    for (const [key, value] of Object.entries(slot)) {
      const clamped = clampValue(key, value)
      if (clamped !== null) state.overrides[key] = clamped
    }
    return state
  } catch {
    return defaultState()
  }
}

/**
 * 功能: 把设置状态写进存储(隐私模式等写失败静默, 沿用项目惯例).
 * @param {{setItem: Function}} storage localStorage 或注入的假对象
 * @param {object} state 设置状态
 * @returns {void}
 */
export function saveDisplayState(storage, state) {
  try {
    storage?.setItem?.(DISPLAY_KEY, JSON.stringify(state))
  } catch {
    /* 写不进就算了, 本次会话内仍生效 */
  }
}

/**
 * 功能: 读取全局背景场景. 与主题显示参数分开存, 切日夜不会换房间。
 * @param {{getItem: Function}} storage localStorage 或注入的假对象
 * @returns {'default'|'laboratory'} 背景场景
 */
export function loadBackgroundScene(storage) {
  try {
    const raw = storage?.getItem?.(BACKGROUND_KEY)
    if (!raw) return DEFAULT_BACKGROUND_SCENE
    const parsed = JSON.parse(raw)
    const value = parsed?.scene
    return BACKGROUND_SCENES.includes(value) ? value : DEFAULT_BACKGROUND_SCENE
  } catch {
    return DEFAULT_BACKGROUND_SCENE
  }
}

/**
 * 功能: 持久化全局背景场景. 无效输入按默认场景落盘。
 * @param {{setItem: Function}} storage localStorage 或注入的假对象
 * @param {*} value 背景场景
 * @returns {'default'|'laboratory'} 实际保存值
 */
export function saveBackgroundScene(storage, value) {
  const scene = BACKGROUND_SCENES.includes(value) ? value : DEFAULT_BACKGROUND_SCENE
  try {
    storage?.setItem?.(BACKGROUND_KEY, JSON.stringify({ version: 1, scene }))
  } catch {
    /* 写不进就算了, 本次会话内仍生效 */
  }
  return scene
}

/**
 * 功能: 把 PALETTES 的 keyPos 方向向量换算成 方位角/仰角(度).
 *       约定: 方位角 = atan2(x, z)(+z 朝向观察者初始位), 仰角 = 相对水平面.
 *       与 fromKeyAngles 严格互逆(方向部分).
 * @param {[number, number, number]} keyPos 主光方向向量
 * @returns {{azimuthDeg: number, elevationDeg: number}} 角度
 */
export function deriveKeyAngles(keyPos) {
  const [x, y, z] = keyPos
  const horizontal = Math.hypot(x, z)
  return {
    azimuthDeg: Math.round((Math.atan2(x, z) * 180) / Math.PI),
    elevationDeg: Math.round((Math.atan2(y, horizontal) * 180) / Math.PI),
  }
}

/**
 * 功能: 方位角/仰角(度) -> 单位方向向量 [x,y,z]. deriveKeyAngles 的逆.
 * @param {number} azimuthDeg 方位角
 * @param {number} elevationDeg 仰角
 * @returns {[number, number, number]} 单位向量
 */
export function fromKeyAngles(azimuthDeg, elevationDeg) {
  const az = (azimuthDeg * Math.PI) / 180
  const el = (elevationDeg * Math.PI) / 180
  const cosEl = Math.cos(el)
  return [Math.sin(az) * cosEl, Math.sin(el), Math.cos(az) * cosEl]
}

/**
 * 功能: 组装「导出参数」的载荷 —— 用户调好的值交回管线/代码固化成新默认用.
 * @param {string} theme 当前主题
 * @param {string} quality 当前画质档
 * @param {object} baseline 全量基准
 * @param {object} overrides 稀疏覆盖
 * @returns {object} 可 JSON 序列化的导出结构
 */
export function exportPayload(theme, quality, baseline, overrides) {
  return {
    version: 2,
    // 昼夜共用一套观感参数, theme 现在只是"导出时在哪个环境下看的"备注
    theme,
    quality,
    overrides: { ...overrides },
    effective: effectiveSettings(baseline, overrides),
  }
}
