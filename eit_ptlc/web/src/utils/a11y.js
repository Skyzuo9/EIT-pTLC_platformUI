// 可达性小工具
// ==============
// pressable: 给"确实不能换成 <button> 的容器行"补上按钮语义与键盘激活。
// 适用面刻意收窄: 只给 NodeRow 这类 grid 行 + 内嵌次级按钮 (button 不能嵌 button) 的场景;
// 其余一律用真 <button class="btn-bare"> (见 style.css), 语义/焦点/触屏全部白得。
//
// 模板用法:
//   <div class="node-row" v-bind="pressable(select)" :aria-selected="active">

/**
 * @param {Function} handler 激活回调 (click 与 Enter/Space 共用)
 * @param {object} [opts]
 * @param {string} [opts.role] 默认 'button'
 * @returns {object} 可 v-bind 的属性包 { role, tabindex, onClick, onKeydown }
 */
export function pressable(handler, { role = 'button' } = {}) {
  return {
    role,
    tabindex: 0,
    onClick: handler,
    onKeydown(e) {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault()
        handler(e)
      }
    },
  }
}
