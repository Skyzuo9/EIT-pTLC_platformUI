<script setup>
// 设备参数面板: app.yaml 的 camera/gcode/vision/pump 段结构化编辑 (扁平化为点号路径字段)
// 嵌入动作/流程页, 复用参数表单范式; 保存经后端 loader 校验 (不通过 400 不写盘)
import { onBeforeUnmount, onMounted, ref, useId, watch } from 'vue'
import { api, errText } from '../api'
import { confirmAction } from '../composables/confirmService.js'
import { paramMeta } from '../deviceParamsMeta'

const SECTIONS = [
  { key: 'camera', label: '相机 (曝光/增益/UV光/图像尺寸)' },
  { key: 'gcode', label: 'CNC (板原点/Z高度/进给/刀具)' },
  { key: 'vision', label: '视觉' },
  { key: 'pump', label: '泵档默认 (吸/打速度/步延时/点样终点)' },
]
const section = ref('camera')
const rows = ref([])
const msg = ref('')
const busy = ref(false)

// 行内 label↔input 关联与浮卡 aria-controls 用的稳定 id 前缀 (同页多实例不串)
const uid = useId()
const popId = `${uid}-pop`
function fieldId(path) {
  return `${uid}-${path}`
}

// 参数释义浮卡: 同时只开一个, null = 关闭; 坐标是视口坐标 (position: fixed)
const pop = ref(null)
const POP_W = 280   // 与 CSS .dp-pop 的 width 同值, 右缘越界翻转靠它算
const POP_GAP = 8   // 卡与视口边 / 锚点按钮的间距

/**
 * 功能:
 *     点 ? 开关该参数的释义浮卡; 同一行再点即关, 点另一行直接换 (故天然只开一个)
 * 参数:
 *     row: 参数行对象, 需已挂 meta (中文名/释义)
 *     ev: 点击事件, 用 currentTarget 的视口矩形定位浮卡
 * 返回:
 *     无, 直接改 pop 状态
 */
function togglePop(row, ev) {
  if (pop.value && pop.value.path === row.path) {
    pop.value = null
    return
  }
  // 用 fixed + 按钮视口矩形定位: 表在 .area-center (overflow: auto) 里, absolute 会被它裁掉
  const rect = ev.currentTarget.getBoundingClientRect()
  let left = rect.left
  if (left + POP_W + POP_GAP > window.innerWidth) {
    left = window.innerWidth - POP_W - POP_GAP   // 右缘越界: 整卡左移贴右边
  }
  if (left < POP_GAP) {
    left = POP_GAP
  }
  // 按钮落在上半屏则用 top 锚点向下长, 下半屏则用 bottom 锚点向上长; 配合 CSS
  // max-height: 46vh (< 半屏 50vh) 保证卡必然装进所选半屏, 无需渲染后测高再翻转
  const down = rect.bottom < window.innerHeight / 2
  pop.value = {
    path: row.path,
    label: row.meta.label,
    desc: row.meta.desc,
    left,
    top: down ? `${rect.bottom + 6}px` : 'auto',
    bottom: down ? 'auto' : `${window.innerHeight - rect.top + 6}px`,
  }
}
function closePop() {
  pop.value = null
}
function onKey(e) {
  if (e.key === 'Escape') {
    pop.value = null
  }
}
// 挂载即注册, 不在开卡时注册: 否则开卡那次 click 仍在冒泡, 会立刻命中新监听器把卡关掉。
// ? 按钮与卡体各自 @click.stop, 所以 document 上的 click 一定是"点在别处", 无脑关即可。
// scroll 必须 capture: 该事件不冒泡, 只有捕获阶段能收到祖先 .area-center 的滚动 (fixed 卡不跟滚)。
// scroll 监听只关卡, 不 preventDefault → passive 明示, 免滚动被标记为可阻塞
const SCROLL_OPTS = { capture: true, passive: true }
onMounted(() => {
  document.addEventListener('click', closePop)
  document.addEventListener('scroll', closePop, SCROLL_OPTS)
  window.addEventListener('keydown', onKey)
})
onBeforeUnmount(() => {
  document.removeEventListener('click', closePop)
  document.removeEventListener('scroll', closePop, SCROLL_OPTS)
  window.removeEventListener('keydown', onKey)
})

function flatten(obj, prefix = '') {
  const out = []
  for (const k of Object.keys(obj || {})) {
    const v = obj[k]
    const path = prefix ? `${prefix}.${k}` : k
    if (v !== null && typeof v === 'object' && !Array.isArray(v)) out.push(...flatten(v, path))
    else out.push({ path, value: v, t: Array.isArray(v) ? 'json' : typeof v })
  }
  return out
}
function unflatten(rs) {
  const out = {}
  for (const r of rs) {
    const parts = r.path.split('.')
    let cur = out
    for (let i = 0; i < parts.length - 1; i++) {
      if (!cur[parts[i]]) cur[parts[i]] = {}
      cur = cur[parts[i]]
    }
    cur[parts[parts.length - 1]] = r.value
  }
  return out
}

async function load() {
  msg.value = ''
  pop.value = null                  // 切段: 行全换, 旧卡锚定的行已不存在
  try {
    const r = await api.getConfigSection(section.value)
    rows.value = flatten(r.values)
    // 逐行预挂中文名/释义, 模板免每次重渲反复查表; 未登记得 null, 模板据此回落只显示原始 key。
    // 查表须带段名: flatten 只产段内路径, camera 与 vision 都有 mock。
    for (const row of rows.value) {
      row.meta = paramMeta(section.value, row.path)
    }
  } catch (e) {
    msg.value = '读取失败: ' + errText(e)
  }
}
async function save() {
  if (!(await confirmAction({
    title: '保存设备参数',
    message: '这些值直接决定机床走位 (板原点/Z 高)、刀具与泵档, 保存即生效。',
    detail: `写入 app.yaml 的 ${section.value} 段`,
    level: 'danger-ack',
    ackText: '我已逐项核对修改的参数',
    confirmText: '保存',
  }))) return
  busy.value = true
  msg.value = ''
  try {
    await api.saveConfigSection(section.value, unflatten(rows.value))
    msg.value = '已保存 ✓ (部分参数需重启上位机生效)'
  } catch (e) {
    msg.value = '保存失败: ' + errText(e)
  } finally {
    busy.value = false
  }
}

watch(section, load)
load()
</script>

<template>
  <div class="dev-params">
    <div class="dp-head">
      <select v-model="section" aria-label="设备参数段">
        <option v-for="s in SECTIONS" :key="s.key" :value="s.key">{{ s.label }}</option>
      </select>
      <button :disabled="busy" :aria-busy="busy" @click="save">{{ busy ? '保存中…' : '保存设备参数' }}</button>
    </div>
    <table class="dp-table">
      <tbody>
        <tr v-for="r in rows" :key="r.path">
          <th>
            <template v-if="r.meta"><label :for="fieldId(r.path)">{{ r.meta.label }}</label><code class="dp-key">{{ r.path }}</code><button
              type="button" class="dp-q" :aria-expanded="!!pop && pop.path === r.path"
              :aria-controls="popId"
              aria-label="参数说明" @click.stop="togglePop(r, $event)">?</button></template>
            <template v-else><label :for="fieldId(r.path)">{{ r.path }}</label></template>
          </th>
          <td>
            <input v-if="r.t === 'number'" :id="fieldId(r.path)" type="number" step="any" v-model.number="r.value" />
            <input v-else-if="r.t === 'boolean'" :id="fieldId(r.path)" type="checkbox" v-model="r.value" />
            <input v-else :id="fieldId(r.path)" type="text" v-model="r.value" />
          </td>
        </tr>
      </tbody>
    </table>
    <p v-if="!rows.length" class="dp-msg">该段无可编辑字段</p>
    <p v-if="msg" class="dp-msg" role="status">{{ msg }}</p>
    <!-- 释义浮卡: Teleport 到 body + fixed, 免被祖先 .area-center 的 overflow: auto 裁掉 -->
    <Teleport to="body">
      <div v-if="pop" :id="popId" class="dp-pop" role="tooltip"
           :style="{ left: pop.left + 'px', top: pop.top, bottom: pop.bottom }" @click.stop>
        <div class="dp-pop-h">{{ pop.label }}<code>{{ pop.path }}</code></div>
        <div class="dp-pop-b">{{ pop.desc }}</div>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.dev-params { margin-top: 10px; }
.dp-head { display: flex; gap: 8px; margin-bottom: 8px; }
.dp-head select { flex: 1; min-width: 0; height: 28px; padding: 3px 8px; border: 1px solid var(--border); border-radius: 5px; background: var(--field-bg); color: var(--text); }
.dp-head button { height: 28px; padding: 3px 10px; border: 1px solid var(--border); border-radius: 5px; background: var(--surface-2); color: var(--text); font-weight: 600; cursor: pointer; }
.dp-head button:hover:not(:disabled) { background: var(--hover); border-color: var(--accent); color: var(--accent); }
.dp-table { border-collapse: collapse; width: auto; font-size: var(--fs-12); line-height: 1.35; }
.dp-table th { text-align: left; padding: 3px 12px 3px 2px; color: var(--subtle); font-weight: 600; font-family: var(--font-ui); font-size: var(--fs-12); white-space: nowrap; }
.dp-table td input[type=text], .dp-table td input[type=number] { width: 200px; min-height: 24px; padding: 2px 6px; color: var(--text); border: 1px solid var(--border); border-radius: 4px; }
.dp-msg { font-size: var(--fs-12); margin-top: 8px; color: var(--muted); }
/* 标签列: 中文名 (主, 继承 th 的 subtle + 600) + 原始 key (灰小号 mono) + ? 释义按钮。
   th 的 white-space: nowrap 保持不变: 最长一行约 300px 加 200px 输入框中区栏放得下,
   一旦允许折行, 点号路径会被折成不可读的两截。 */
.dp-key { margin-left: 6px; font-family: var(--font-mono); font-size: var(--fs-11); font-weight: 400; color: var(--muted-soft); }
.dp-q { margin-left: 6px; width: 16px; height: 16px; padding: 0; line-height: 14px; text-align: center;
  border: 1px solid var(--border); border-radius: 50%; background: var(--surface-2); color: var(--muted);
  font-size: var(--fs-11); cursor: pointer; vertical-align: middle; }
.dp-q:hover { background: var(--hover); border-color: var(--accent); color: var(--accent); }
/* 释义浮卡: 照 .gantt-tip 的浮卡语汇与 z-index 1200 (项目既有浮动提示层级), 但本卡可点可滚,
   故不带它那条 pointer-events: none。max-height 46vh 与 togglePop 的上下半屏锚点切换配套。 */
.dp-pop { position: fixed; z-index: 1200; width: 280px; max-height: 46vh; overflow-y: auto;
  background: var(--panel); border: 1px solid var(--border); border-radius: 8px;
  box-shadow: 0 6px 24px rgba(0, 0, 0, 0.18); padding: 8px 10px; font-size: var(--fs-12); line-height: 1.5; }
.dp-pop-h { font-weight: 600; color: var(--text); margin-bottom: 4px; }
.dp-pop-h code { margin-left: 5px; font-family: var(--font-mono); font-size: var(--fs-11); font-weight: 400; color: var(--muted-soft); }
.dp-pop-b { color: var(--muted); white-space: pre-line; }   /* desc 用 \n 分段, 靠 pre-line 渲染 */
</style>
