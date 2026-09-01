/**
 * 功能: 右键"单击 vs 拖拽平移"判定器(纯逻辑, 可 node --test).
 *
 * canvas 的右键被 camera-controls 占用(右键拖拽=TRUCK 平移), 产品决策是两个习惯
 * 都保留: 右键**单击**(按下到 contextmenu 位移 < 阈值)弹快捷菜单, 右键**按住拖拽**
 * 仍平移视角. contextmenu 事件发生在 pointerup 之后, 按 pointerdown 记下的落点
 * 与 contextmenu 坐标的距离裁决.
 *
 * @param {number} [threshold=4] 判定阈值(px, 与两个场景既有的 4px 点击判定同数)
 * @returns {{onPointerDown: Function, shouldOpen: Function, reset: Function}} 判定器
 */
export function createRightClickTracker(threshold = 4) {
  let down = null
  return {
    /**
     * 功能: 记录右键按下位置(其余按键忽略).
     * @param {PointerEvent} event 指针事件
     * @returns {void}
     */
    onPointerDown(event) {
      if (event.button === 2) down = { x: event.clientX, y: event.clientY }
    },
    /**
     * 功能: contextmenu 时刻裁决是否该弹菜单(裁决后状态复位).
     * @param {MouseEvent} event contextmenu 事件
     * @returns {boolean} 位移小于阈值(单击)返回 true
     */
    shouldOpen(event) {
      // 无 down 记录的路径(键盘菜单键等)不弹 —— 语义上不是"右击了某个零件"
      if (!down) return false
      const moved = Math.hypot(event.clientX - down.x, event.clientY - down.y)
      down = null
      return moved < threshold
    },
    /**
     * 功能: 强制复位(场景销毁等).
     * @returns {void}
     */
    reset() {
      down = null
    },
  }
}
