/**
 * 功能: 合并块成员的包围盒线框高亮 —— 悬浮候选/成员行时画出该零件在哪.
 *
 * 成员几何已被 join 融进 STATIC 块, 无法按网格描边高亮, 包围盒线框是 bbox 候选
 * 路线下唯一可行的"指认"手段. 线框挂在 glTF y-up 模型空间节点(machineRoot 的
 * 第一个子节点)下, 管线记录的 bbox {c,s} 坐标**直接使用**, 不做任何单位换算 ——
 * 口径由 blender_clean 的 _to_gl 与前端 worldToLocal 共同锁定. 场景是米制.
 *
 * 支持一次画多个盒: 同一零件的多个装配实例(侧门-1/侧门-2)要一起亮, 否则用户
 * 会以为只有一个, 拆出时就只拆了一半(实际踩过).
 *
 * 两种样式: 实线=悬浮指认; 虚线=已标"拆出待生效"的持续提示.
 */
import * as THREE from 'three'

export class BboxHighlighter {
  /**
   * 功能: 建立高亮器.
   * @param {THREE.Object3D} modelSpace glTF y-up 模型空间节点(bbox 坐标的宿主)
   */
  constructor(modelSpace) {
    this.modelSpace = modelSpace
    /** @type {THREE.LineSegments[]} 当前线框(每次 show 重建, 保证虚线间距正确) */
    this.lines = []
  }

  /**
   * 功能: 显示一个或一组成员的包围盒线框(重复调用自动替换).
   * @param {object|Array} member 归一成员或成员数组
   * @param {{dashed?: boolean}} [opts] dashed=虚线样式(待生效标记)
   * @returns {number} 实际画出的盒数(无 bbox 的旧格式成员不计)
   */
  show(member, { dashed = false } = {}) {
    this.hide()
    if (!this.modelSpace || !member) return 0
    const list = Array.isArray(member) ? member : [member]
    const color = this._accentColor()
    for (const entry of list) {
      const box = entry?.bbox
      if (!box || !Array.isArray(box.c) || !Array.isArray(box.s)) continue
      // 每次按真实尺寸重建几何: LineDashedMaterial 的间距按顶点距离预计算,
      // 复用单位盒再缩放会让虚线随盒子尺寸拉伸变形.
      // 场景是米制, 最小边压到 1mm 免得零厚度薄板画不出线框
      const geometry = new THREE.EdgesGeometry(
        new THREE.BoxGeometry(
          Math.max(box.s[0], 0.001),
          Math.max(box.s[1], 0.001),
          Math.max(box.s[2], 0.001),
        ),
      )
      const material = dashed
        ? new THREE.LineDashedMaterial({
            color,
            transparent: true,
            opacity: 0.85,
            depthTest: false,
            dashSize: 0.05,
            gapSize: 0.03,
          })
        : new THREE.LineBasicMaterial({ color, transparent: true, opacity: 0.95, depthTest: false })
      const line = new THREE.LineSegments(geometry, material)
      if (dashed) line.computeLineDistances()
      line.position.set(box.c[0], box.c[1], box.c[2])
      // 关深度测试后靠渲染顺序压在模型之上, 保证被遮挡的实例也能看清位置
      line.renderOrder = 999
      line.name = 'MEMBER_BBOX_HIGHLIGHT'
      this.modelSpace.add(line)
      this.lines.push(line)
    }
    return this.lines.length
  }

  /**
   * 功能: 隐藏并释放当前全部线框.
   * @returns {void}
   */
  hide() {
    for (const line of this.lines) {
      line.parent?.remove(line)
      line.geometry?.dispose()
      line.material?.dispose()
    }
    this.lines.length = 0
  }

  /**
   * 功能: 释放全部资源(视图卸载时调用).
   * @returns {void}
   */
  dispose() {
    this.hide()
    this.modelSpace = null
  }

  /**
   * 功能: 取当前主题的强调色(浅深色主题各自正确).
   * @returns {THREE.Color} 颜色
   */
  _accentColor() {
    const text = getComputedStyle(document.body).getPropertyValue('--accent').trim()
    return new THREE.Color(text || '#36d1ff')
  }
}
