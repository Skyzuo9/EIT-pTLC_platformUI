/**
 * 功能: 把上位机 <html data-theme> 转为三维场景可订阅的昼夜主题.
 */

/**
 * 功能: 读取宿主当前主题.
 * @returns {'dark'|'light'} 三维场景主题名
 */
export function getTheme() {
  return document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light'
}

/**
 * 功能: 订阅宿主主题属性变化, 供场景热更新背景、灯光和描边.
 * @param {(theme: 'dark'|'light') => void} callback 主题变更回调
 * @returns {() => void} 取消订阅函数
 */
export function onThemeChange(callback) {
  let current = getTheme()
  const observer = new MutationObserver(() => {
    const next = getTheme()
    if (next === current) return
    current = next
    callback(next)
  })
  observer.observe(document.documentElement, {
    attributes: true,
    attributeFilter: ['data-theme'],
  })
  return () => observer.disconnect()
}
