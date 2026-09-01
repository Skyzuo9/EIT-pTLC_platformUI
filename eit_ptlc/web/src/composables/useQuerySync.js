// UI 状态 ⇄ URL query 双向同步 (页签/缩放/选中项刷新不丢、可深链分享)
// ======================================================================
// 写方向用 router.replace (不淤浏览器历史); 值等于默认值时从 query 删键保持 URL 干净。
// 路由参数型状态 (如 /materials/:cat) 不用本原语 —— 那是身份, 本原语只管视图状态。
import { watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

/**
 * @param {string} key query 键名
 * @param {import('vue').Ref} target 被同步的 ref
 * @param {object} [opts]
 * @param {Function} [opts.parse] (str) => value, 默认原样字符串
 * @param {Function} [opts.serialize] (value) => str, 默认 String()
 * @param {*} [opts.defaultValue] 等于此值时从 URL 删键; 后退到无键时也回落到此值
 */
export function useQuerySync(key, target, { parse = (v) => v, serialize = (v) => String(v), defaultValue } = {}) {
  const route = useRoute()
  const router = useRouter()

  // 初始: URL → ref (非法值忽略, 保留调用方初值)
  const init = route.query[key]
  if (init != null) {
    try {
      target.value = parse(Array.isArray(init) ? init[0] : init)
    } catch (_e) {
      /* 忽略 */
    }
  }

  // ref → URL
  watch(target, (v) => {
    const next = { ...route.query }
    const isDefault = defaultValue !== undefined && v === defaultValue
    if (isDefault || v == null || v === '') delete next[key]
    else next[key] = serialize(v)
    const cur = route.query[key]
    if ((cur == null ? undefined : String(cur)) === next[key]) return
    router.replace({ query: next }).catch(() => {})
  })

  // URL → ref (后退/前进/外部改 URL)
  watch(
    () => route.query[key],
    (v) => {
      if (v == null) {
        if (defaultValue !== undefined && target.value !== defaultValue) target.value = defaultValue
        return
      }
      try {
        const parsed = parse(Array.isArray(v) ? v[0] : v)
        if (parsed !== target.value) target.value = parsed
      } catch (_e) {
        /* 忽略 */
      }
    },
  )
}
