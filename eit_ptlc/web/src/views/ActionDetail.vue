<script setup>
// 动作编辑/点测 IDE: 与流程编辑器同形的工具栏 + 主工作区 + 右侧参数/文档/注释页签。
import { computed, ref, useId, watch } from 'vue'
import { useRoute } from 'vue-router'
import { api, errText } from '../api'
import { useSystemStore } from '../store'
import { useEditorStore } from '../stores/editor'
import CodeEditor from '../components/CodeEditor.vue'
import Splitter from '../components/Splitter.vue'
import { confirmAction } from '../composables/confirmService.js'
import { useAsyncAction } from '../composables/useAsyncAction.js'
import { useDirtyGuard } from '../composables/useDirtyGuard.js'
import { useQuerySync } from '../composables/useQuerySync.js'
import { useRovingTabs } from '../composables/useRovingTabs.js'
import { useLayoutStore } from '../stores/layout'
import { useThemeStore } from '../stores/theme'
import { toDisplay, toRaw } from '../utils/runInputs'

const route = useRoute()
const sys = useSystemStore()
const editor = useEditorStore()
const layout = useLayoutStore()
const themeStore = useThemeStore()

const action = ref(null)
const paramValues = ref({})
const result = ref(null)
const rightTab = ref('param')
// 页签键盘巡航 (roving tabindex): 组内 ←→ 切换, Tab 一站穿出
const rightRoving = useRovingTabs(['param', 'doc', 'note'], rightTab)
const tab = ref('form')
const uid = useId()   // 参数表单 label/控件 for-id 前缀 (参数名跨动作可重复, 单靠 p.name 不够唯一)

const descDraft = ref('')
const descOriginal = ref('')
const descMsg = ref('')
const descBusy = ref(false)
const descDirty = computed(() => descDraft.value !== descOriginal.value)

const rawText = ref('')
const rawOriginal = ref('')
const rawPath = ref('')
const rawMsg = ref('')
const rawBusy = ref(false)
const rawLoaded = ref(false)
const rawDirty = computed(() => rawLoaded.value && rawText.value !== rawOriginal.value)

const currentDirty = computed(() => tab.value === 'yaml' ? rawDirty.value : descDirty.value)
const currentBusy = computed(() => tab.value === 'yaml' ? rawBusy.value : descBusy.value)
const identPath = computed(() => rawPath.value || (
  action.value ? `config/actions/${action.value.group || '未分组'}/${action.value.name}` : ''
))

function initParams() {
  paramValues.value = {}
  if (!action.value) return
  for (const p of action.value.params) {
    if (p.default !== null && p.default !== undefined) paramValues.value[p.name] = p.default
  }
}

// 缩放参数 (p.scale) 提交: 界面物理值 (如 mL/min) 换回底层原值 (整数 V) 存入 paramValues,
// 使 runAction 下发 / 后端校验仍走 V (显示皮肤不改下发单位); 留空=不传, 走泵档默认。
// 末尾强制把输入框回写为吸附后的显示值: Vue 受控 :value 在 model 未变时不重渲 DOM,
// 手动同步才能保证"显示恒等于真实下发值"(如输 1.6 恒回显 1.5)。
function onScaledParam(p, ev) {
  const raw = toRaw(ev.target.value, p.scale, p.minimum, p.maximum)
  paramValues.value[p.name] = raw === '' ? undefined : Number(raw)
  ev.target.value = toDisplay(raw, p.scale)
}

async function loadRaw() {
  rawMsg.value = ''
  rawLoaded.value = false
  if (!route.params.name) return
  try {
    const r = await api.getActionRaw(route.params.name)
    rawText.value = r.text
    rawOriginal.value = r.text
    rawPath.value = r.path
    rawLoaded.value = true
  } catch (e) {
    rawMsg.value = '读取失败: ' + errText(e)
  }
}

async function load() {
  action.value = null
  result.value = null
  descMsg.value = ''
  if (!route.params.name) return
  action.value = await api.getAction(route.params.name)
  descDraft.value = action.value.desc || ''
  descOriginal.value = descDraft.value
  initParams()
  await loadRaw()
}

// 执行 = 向真实设备下发一次原子动作: danger 确认闸门在前, 下发经 useAsyncAction (busy/连发保护);
// 结果 (含 ERROR) 仍落 result 面板, 保持原视觉落点
const execAction = useAsyncAction(async () => {
  result.value = await api.runAction(action.value.name, paramValues.value, sys.mode)
  return result.value
}, {
  announce: (r) => (r && r.status === 'DONE' ? '执行完成' : `执行结束: ${(r && r.status) || '未知'}`),
  errorPrefix: '执行失败',
  onError: (_msg, e) => { result.value = { status: 'ERROR', message: errText(e) } },
})

async function run() {
  if (!action.value) return
  if (!(await confirmAction({
    title: `执行动作 ${action.value.label || action.value.name}`,
    message: '将向真实设备下发一次原子动作。',
    detail: action.value.name,
    level: 'danger',
    confirmText: '执行',
  }))) return
  await execAction.run()
}

async function saveDescription() {
  if (!action.value || !descDirty.value) return
  descBusy.value = true
  descMsg.value = ''
  try {
    action.value = await api.saveActionDescription(action.value.name, descDraft.value)
    descDraft.value = action.value.desc
    descOriginal.value = action.value.desc
    descMsg.value = '动作说明已保存并热重载 ✓'
    await editor.refreshActions()
    // 定点保存已经改了磁盘源文件，立即重拉 YAML，避免隐藏的旧缓冲覆盖新说明。
    await loadRaw()
  } catch (e) {
    descMsg.value = '保存失败: ' + errText(e)
  } finally {
    descBusy.value = false
  }
}

async function saveRaw() {
  if (!rawLoaded.value || !rawDirty.value) return
  rawBusy.value = true
  rawMsg.value = ''
  try {
    const r = await api.saveActionRaw(route.params.name, rawText.value)
    rawOriginal.value = rawText.value
    rawMsg.value = '已保存 ✓' + (r.actions ? ` (${r.actions} 个动作已重载)` : '')
    await editor.refreshActions()
    action.value = await api.getAction(route.params.name)
    descDraft.value = action.value.desc || ''
    descOriginal.value = descDraft.value
  } catch (e) {
    rawMsg.value = '保存失败: ' + errText(e)
  } finally {
    rawBusy.value = false
  }
}

function saveCurrent() {
  return tab.value === 'yaml' ? saveRaw() : saveDescription()
}

function discardCurrent() {
  if (tab.value === 'yaml') rawText.value = rawOriginal.value
  else descDraft.value = descOriginal.value
}

// 未保存守卫: 路由 update(:name 换动作)/leave/beforeunload 三口全拦; 脏判据 = 说明或 YAML 任一有草稿
const { confirmDiscard } = useDirtyGuard(() => descDirty.value || rawDirty.value, {
  message: '当前动作有未保存修改, 离开将丢弃。',
  paramKey: 'name',
})

async function switchTab(next) {
  if (next === tab.value) return
  // 只看当前视图的脏 (另一视图的草稿不因本次切换丢失, 不该拦)
  if (currentDirty.value && !(await confirmDiscard('当前视图有未保存修改, 切换将丢弃。'))) return
  discardCurrent()
  tab.value = next
}

watch(() => route.params.name, () => {
  tab.value = 'form'
  rightTab.value = 'param'
  descDraft.value = ''
  descOriginal.value = ''
  rawText.value = ''
  rawOriginal.value = ''
  rawPath.value = ''
  rawMsg.value = ''
  rawLoaded.value = false
  load()
}, { immediate: true })

// 页签深链: 必须接在上面 immediate watch 之后, 首帧的 tab 复位才不会盖掉 URL 值
useQuerySync('tab', tab, { defaultValue: 'form' })

// 左栏「改显示名」落盘后: 同步本页 label 并重拉 YAML 源码, 防旧缓冲整文件保存回写旧 label
watch(() => editor.actionsCache.find((a) => a.name === route.params.name)?.label, async (nl) => {
  if (!action.value || nl === undefined || nl === action.value.label) return
  action.value = { ...action.value, label: nl }
  await loadRaw()
})
</script>

<template>
  <p v-if="!route.params.name" class="empty">从左侧「库 > 动作」选择一个原子指令</p>
  <div v-else class="action-editor">
    <div class="editor-toolbar action-toolbar">
      <button class="tb" :class="{ selected: tab === 'form' }" @click="switchTab('form')">动作执行</button>
      <button class="tb" :class="{ selected: tab === 'yaml' }" @click="switchTab('yaml')">YAML 源文件</button>
      <span class="tb-grow" />
      <span v-if="action" class="doc-ident" :title="identPath">
        {{ action.label }}<small>{{ identPath }}</small>
      </span>
      <span v-if="currentDirty" class="dirty-tag">未保存</span>
      <button class="tb save" :disabled="currentBusy || !currentDirty" @click="saveCurrent">
        {{ currentBusy ? '保存中…' : (currentDirty ? '保存 *' : '已保存') }}
      </button>
    </div>

    <div class="action-page" :style="{ '--action-params-w': layout.sizes.actionParamsW + 'px' }">
      <section class="detail">
        <p v-if="!action" class="empty loading">正在读取动作定义…</p>
        <template v-else>
          <div v-if="tab === 'form'">
            <h2>{{ action.label }} <small>{{ action.name }}</small></h2>
            <p class="muted">{{ action.params.length ? '填写本次点测参数；动作定义与流程调用共用同一执行路径。' : '该动作无参数；动作定义与流程调用共用同一执行路径。' }}</p>
            <div v-if="action.params.length" class="form">
              <div v-for="p in action.params" :key="p.name" class="field">
                <label v-if="p.type === 'bool'" class="bool-row">
                  <input type="checkbox" v-model="paramValues[p.name]" />
                  <span>{{ p.label }} <span v-if="p.required" class="req">*</span></span>
                </label>
                <template v-else>
                  <label :for="`${uid}-${p.name}`">
                    {{ p.label }} <span v-if="p.required" class="req">*</span>
                    <small v-if="p.minimum != null || p.maximum != null" class="range">
                      [{{ p.scale ? toDisplay(p.minimum, p.scale) : (p.minimum ?? '') }}–{{ p.scale ? toDisplay(p.maximum, p.scale) : (p.maximum ?? '') }}{{ p.scale && p.unit ? ' ' + p.unit : '' }}]
                    </small>
                  </label>
                  <!-- 判据只看有没有取值域 (与后端 executor 同一条规则), 不看 type -->
                  <select v-if="p.options && p.options.length" :id="`${uid}-${p.name}`" v-model="paramValues[p.name]">
                    <option :value="undefined">{{ p.type === 'point_ref' ? '-- 选择点位 --' : '--' }}</option>
                    <option v-for="o in p.options" :key="o.value" :value="o.value">{{ o.label }}</option>
                  </select>
                  <span v-else-if="(p.type === 'int' || p.type === 'float') && p.scale" class="scaled-in">
                    <input :id="`${uid}-${p.name}`" :name="p.name" type="number" inputmode="decimal"
                           :min="toDisplay(p.minimum, p.scale)" :max="toDisplay(p.maximum, p.scale)" :step="p.scale"
                           :placeholder="p.default_hint != null ? `${toDisplay(p.default_hint, p.scale)} · 泵档默认` : ''"
                           :value="toDisplay(paramValues[p.name], p.scale)"
                           @change="onScaledParam(p, $event)" />
                    <small v-if="p.unit" class="unit">{{ p.unit }}</small>
                  </span>
                  <input v-else-if="p.type === 'int' || p.type === 'float'" :id="`${uid}-${p.name}`" :name="p.name" type="number"
                         :inputmode="p.type === 'int' ? 'numeric' : 'decimal'"
                         :min="p.minimum" :max="p.maximum" :step="p.type === 'int' ? 1 : 'any'"
                         :placeholder="p.default_hint != null ? `${p.default_hint} · 泵档默认` : ''"
                         v-model.number="paramValues[p.name]" />
                  <input v-else :id="`${uid}-${p.name}`" :name="p.name" type="text" spellcheck="false" v-model="paramValues[p.name]" />
                  <router-link v-if="p.is_point && paramValues[p.name]" class="pt-jump"
                     :to="`/points/robot/${encodeURIComponent(paramValues[p.name])}`"
                     title="跳转到点位管理页查看/修改">→ 点位</router-link>
                </template>
              </div>
            </div>
            <button class="run" :disabled="execAction.busy" :aria-busy="execAction.busy" @click="run">{{ execAction.busy ? '执行中…' : '执行' }}</button>
            <pre v-if="result" class="result" :class="result.status">{{ JSON.stringify(result, null, 2) }}</pre>
          </div>

          <div v-else class="raw-pane">
            <div class="raw-head"><span class="raw-path">{{ rawPath }}</span></div>
            <CodeEditor v-if="rawLoaded" v-model="rawText" :theme="themeStore.theme" />
            <p v-else class="empty loading">正在读取 YAML…</p>
            <p v-if="rawMsg" class="raw-msg" role="status">{{ rawMsg }}</p>
            <p class="muted">编辑整个源文件；顶部「保存」会先执行 YAML、动作 schema、desc 必填及跨文件动作名唯一校验，成功后立即热重载。</p>
          </div>
        </template>
      </section>

      <aside class="dev-params-col right-panel">
        <template v-if="action">
          <div class="dock-tabs" role="tablist" aria-label="动作右栏页签">
            <button type="button" class="dock-tab" role="tab" id="ad-tab-param" aria-controls="ad-panel-param" :tabindex="rightRoving.tabindex('param')" :aria-selected="rightTab === 'param'" :class="{ active: rightTab === 'param' }" @click="rightTab = 'param'" @keydown="rightRoving.onKeydown">参数</button>
            <button type="button" class="dock-tab" role="tab" id="ad-tab-doc" aria-controls="ad-panel-doc" :tabindex="rightRoving.tabindex('doc')" :aria-selected="rightTab === 'doc'" :class="{ active: rightTab === 'doc' }" @click="rightTab = 'doc'" @keydown="rightRoving.onKeydown">文档</button>
            <button type="button" class="dock-tab" role="tab" id="ad-tab-note" aria-controls="ad-panel-note" :tabindex="rightRoving.tabindex('note')" :aria-selected="rightTab === 'note'" :class="{ active: rightTab === 'note' }" @click="rightTab = 'note'" @keydown="rightRoving.onKeydown">注释</button>
          </div>

          <div v-show="rightTab === 'param'" class="action-side-panel" id="ad-panel-param" role="tabpanel" aria-labelledby="ad-tab-param">
            <h4>{{ action.label }}</h4>
            <table class="kv action-meta">
              <tr><td>动作ID</td><td>{{ action.name }}</td></tr>
              <tr><td>类别</td><td>{{ action.kind }}</td></tr>
              <tr><td>模式</td><td>{{ action.modes.join('/') || '不限' }}</td></tr>
              <tr v-if="action.station"><td>工位</td><td>{{ action.station }}</td></tr>
              <tr v-if="action.action_code"><td>动作码</td><td>{{ action.action_code }}</td></tr>
              <tr v-if="action.method"><td>方法</td><td>{{ action.method }}</td></tr>
            </table>
            <h4>参数定义</h4>
            <table v-if="action.params.length" class="kv">
              <thead>
                <tr><th>参数</th><th>类型</th></tr>
              </thead>
              <tbody>
                <tr v-for="p in action.params" :key="p.name">
                  <td>{{ p.label }}<small>{{ p.name }}</small></td>
                  <td>{{ p.type }}{{ p.required ? ' *' : '' }}</td>
                </tr>
              </tbody>
            </table>
            <p v-else class="empty">无参数</p>
          </div>

          <div v-show="rightTab === 'doc'" class="action-side-panel" id="ad-panel-doc" role="tabpanel" aria-labelledby="ad-tab-doc">
            <h4>动作说明</h4>
            <p class="note-text">{{ action.desc }}</p>
            <div v-if="action.plc_link" class="plc-link">
              <div class="plc-link-title">执行关联</div>
              <p>{{ action.plc_link }}</p>
            </div>
          </div>

          <div v-show="rightTab === 'note'" class="note-panel" id="ad-panel-note" role="tabpanel" aria-labelledby="ad-tab-note">
            <textarea v-model="descDraft" class="note-area" aria-label="动作说明文档"
                      placeholder="执行步骤：…&#10;前置与安全：…&#10;完成与异常：…"></textarea>
            <p class="muted">编辑动作的唯一说明真源；顶部「保存」只定点修改当前动作的 desc。</p>
            <p v-if="descMsg" class="raw-msg" role="status">{{ descMsg }}</p>
          </div>
        </template>
      </aside>
      <Splitter skey="actionParamsW" dir="x" :sign="-1" class="seam-action-v" />
    </div>
  </div>
</template>

<style scoped>
.action-editor { display: grid; grid-template-rows: auto minmax(0, 1fr); gap: 8px; height: 100%; }
.action-toolbar .tb.selected { background: var(--accent); color: var(--on-accent); border-color: var(--accent); }
.dirty-tag { color: var(--warn); font-size: var(--fs-12); font-weight: 700; }
.action-side-panel { padding-top: 4px; }
.action-side-panel h4 { margin: 10px 0 6px; }
.action-meta td:last-child { font-family: var(--font-mono); overflow-wrap: anywhere; }
.action-side-panel td small { display: block; color: var(--muted); font-family: var(--font-mono); }
.note-text { margin: 0; font-size: var(--fs-13); line-height: 1.65; color: var(--text); white-space: pre-wrap; overflow-wrap: anywhere; }
.note-panel { min-height: 100%; display: flex; flex-direction: column; gap: 8px; }
.note-area { flex: 1; width: 100%; min-height: 300px; resize: vertical; padding: 8px; border: 1px solid var(--border);
  border-radius: 6px; background: var(--field-bg); color: var(--text); font-family: var(--font-ui); font-size: var(--fs-13); line-height: 1.65; }
.plc-link { margin: 12px 0; padding: 8px 10px; border: 1px solid var(--border); border-left: 3px solid var(--accent);
  border-radius: 6px; background: var(--surface-2); }
.plc-link-title { font-size: var(--fs-12); font-weight: 700; color: var(--subtle); margin-bottom: 4px; }
.plc-link p { margin: 0; font-size: var(--fs-12); color: var(--text); line-height: 1.5; overflow-wrap: anywhere; }
.pt-jump { margin-left: 8px; color: var(--accent); cursor: pointer; font-size: var(--fs-12); font-weight: 600; }
.bool-row { display: flex; flex-direction: row; align-items: center; gap: 8px; cursor: pointer; }
.bool-row input[type="checkbox"] { flex: none; margin: 0; }
.raw-head { display: flex; gap: 8px; align-items: center; margin-bottom: 6px; }
.raw-path { color: var(--muted); font-size: var(--fs-11); font-family: var(--font-mono); overflow-wrap: anywhere; }
.raw-msg { margin: 0; font-family: var(--font-mono); font-size: var(--fs-12); }
/* 缩放数值输入: 数字框 + 单位标并排, 数字框占满字段宽 */
.scaled-in { display: flex; align-items: center; gap: 6px; }
.scaled-in input { flex: 1; min-width: 0; }
.scaled-in .unit { color: var(--muted); font-size: var(--fs-12); white-space: nowrap; }
/* h2 标题样式已上提全局 (.detail h2, style.css) */
/* 全局 .kv 只给 td 样式, 参数定义表补 thead 需自设 th (照 NodeDetail .tanks th) */
.action-side-panel .kv th { border-bottom: 1px solid var(--border); padding: 4px 6px; text-align: left; color: var(--subtle); font-weight: 600; }
</style>
