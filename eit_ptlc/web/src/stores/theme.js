// 主题 store: 全局深/浅主题 (driven by <html data-theme>) + localStorage 持久化
// 协议:
//   - 单一开关 light/dark, 经 <html data-theme> 驱动 style.css 的 :root 与 [data-theme="dark"] 令牌
//   - 代码编辑器 (CodeMirror) 主题跟随本 store (见 PouEditor/ActionDetail 的 :theme 绑定)
//   - 初值由 index.html 内联脚本在挂载前写入 documentElement.dataset.theme (防首屏闪烁), 此处读回
import { defineStore } from 'pinia'
import { ref } from 'vue'

const STORAGE_KEY = 'ptlc.theme'

export const useThemeStore = defineStore('theme', () => {
  // 初值: 取 <html data-theme> (内联脚本已置好), 缺省浅色
  const theme = ref(document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light')

  /**
   * 功能:
   *     应用主题 (单一写入口): 同步响应式状态 + <html data-theme> + 落盘
   * 参数:
   *     next 字符串, 目标主题 'dark' | 'light' (其它值按 'light' 处理)
   * 返回:
   *     None
   */
  function setTheme(next) {
    const value = next === 'dark' ? 'dark' : 'light'
    theme.value = value
    document.documentElement.dataset.theme = value
    // 同步浏览器 UI 底色 (index.html 的 theme-color meta; 值须与 style.css 的 --bg 成对)
    const meta = document.querySelector('meta[name="theme-color"]')
    if (meta) meta.content = value === 'dark' ? '#0f1522' : '#f5f6f8'
    try {
      localStorage.setItem(STORAGE_KEY, value)
    } catch (e) {
      /* localStorage 不可用时静默忽略, 不影响交互 */
    }
  }

  // 在 深/浅 之间翻转
  function toggle() {
    setTheme(theme.value === 'dark' ? 'light' : 'dark')
  }

  return { theme, setTheme, toggle }
})
