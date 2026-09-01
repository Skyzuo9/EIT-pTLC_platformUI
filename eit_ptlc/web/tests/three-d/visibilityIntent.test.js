/**
 * 功能: `node.visible` 多写者仲裁的单元测试.
 *
 * 这一层要钉的性质只有一条, 但它有两个方向, 漏哪个都会出真实的 bug:
 *   1. **有人还藏着就别显示** —— 在动作页隔离过零件之后播一段注液, 液面盒不该自己
 *      弹回画面(ViewTools.isolate 按 `child.isMesh` 收集, 而 LIQUID_* 是裸网格必被藏);
 *   2. **人都撤了就得显示** —— 否则取消隔离之后液面永远回不来, 比第一条更难发现.
 *
 * 用普通对象当桩(仲裁只碰 userData 与 visible), 不引 three —— 这一层没有任何几何。
 */
import assert from 'node:assert/strict'
import test from 'node:test'

import {
  HIDE_OWNER, hasHideIntent, holdHidden, isHiddenByAny, releaseHidden, setHidden,
} from '../../src/three-d/twin/scene/visibilityIntent.js'

/** 造一个最小节点桩 */
function makeNode() {
  return { userData: {}, visible: true }
}

test('单方登记即隐藏, 撤销即恢复', () => {
  const node = makeNode()
  holdHidden(node, HIDE_OWNER.EMPTY)
  assert.equal(node.visible, false)
  assert.equal(isHiddenByAny(node), true)

  releaseHidden(node, HIDE_OWNER.EMPTY)
  assert.equal(node.visible, true)
  assert.equal(isHiddenByAny(node), false)
})

test('多方登记时, 撤销其中一方仍保持隐藏 —— 这是整个模块存在的理由', () => {
  const node = makeNode()
  holdHidden(node, HIDE_OWNER.VIEW)      // 用户隔离
  holdHidden(node, HIDE_OWNER.EMPTY)     // 缸排空了

  // 缸重新注液: 驱动撤销自己那条, 但用户的隔离还在
  releaseHidden(node, HIDE_OWNER.EMPTY)
  assert.equal(node.visible, false, '隔离期间注液, 液面盒不该弹回画面')

  // 用户取消隔离: 此时已无人登记, 才真的显示
  releaseHidden(node, HIDE_OWNER.VIEW)
  assert.equal(node.visible, true, '人都撤了还不显示, 液面就永远回不来了')
})

test('撤销顺序不影响结果(与谁先谁后无关)', () => {
  const node = makeNode()
  holdHidden(node, HIDE_OWNER.VIEW)
  holdHidden(node, HIDE_OWNER.EMPTY)

  releaseHidden(node, HIDE_OWNER.VIEW)
  assert.equal(node.visible, false)
  releaseHidden(node, HIDE_OWNER.EMPTY)
  assert.equal(node.visible, true)
})

test('无人登记时采用调用方的权威值 —— ViewTools 靠这条不点亮"减配视图"藏起的零件', () => {
  const node = makeNode()
  // ViewTools.hide 记下原值(此处为 false: 被圈外机制藏着), 再登记自己的意图
  node.visible = false
  holdHidden(node, HIDE_OWNER.VIEW)
  // showAll: 撤销意图, 已无人登记 -> 还原成台账里记的 false, 而不是无条件 true
  releaseHidden(node, HIDE_OWNER.VIEW, false)
  assert.equal(node.visible, false, '别的机制藏起来的东西不归 ViewTools 管, 不该被误点亮')
})

test('从没登记过的节点也能安全撤销(采用权威值, 不建表)', () => {
  const node = makeNode()
  assert.equal(hasHideIntent(node), false)
  releaseHidden(node, HIDE_OWNER.VIEW, false)
  assert.equal(node.visible, false)
  assert.equal(hasHideIntent(node), false, '空撤销不该凭空建出登记表')
})

test('setHidden 是 hold/release 的开关式写法, 可反复写同一个值(幂等)', () => {
  const node = makeNode()
  for (let i = 0; i < 3; i += 1) setHidden(node, HIDE_OWNER.EMPTY, true)
  assert.equal(node.visible, false)
  setHidden(node, HIDE_OWNER.EMPTY, false)
  assert.equal(node.visible, true)
  // 重复登记不该攒出多条, 撤一次就该干净
  assert.equal(isHiddenByAny(node), false)
})

test('null 节点静默忽略, 不炸(ViewTools 的入参来自用户选择, 可能有空洞)', () => {
  assert.doesNotThrow(() => holdHidden(null, HIDE_OWNER.VIEW))
  assert.doesNotThrow(() => releaseHidden(undefined, HIDE_OWNER.VIEW))
  assert.equal(isHiddenByAny(null), false)
})
